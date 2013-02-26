#ifndef RDB_PROTOCOL_ERR_HPP_
#define RDB_PROTOCOL_ERR_HPP_

#include <list>
#include <string>

#include "utils.hpp"

#include "containers/archive/stl_types.hpp"
#include "rdb_protocol/ql2.pb.h"
#include "rdb_protocol/ql2_extensions.pb.h"
#include "rpc/serialize_macros.hpp"

namespace ql {

// NOTE: you usually want to inherit from `rcheckable_t` instead of calling this
// directly.
void runtime_check(const char *test, const char *file, int line,
                   bool pred, std::string msg, const Backtrace *bt_src);
void runtime_check(const char *test, const char *file, int line,
                   bool pred, std::string msg);
void runtime_sanity_check(bool test);

// Inherit from this in classes that wish to use `rcheck`
class rcheckable_t {
public:
    virtual ~rcheckable_t() { }
    virtual void runtime_check(const char *test, const char *file, int line,
                               bool pred, std::string msg) const = 0;
};
class pb_rcheckable_t : public rcheckable_t {
public:
    pb_rcheckable_t(const Term2 *t)
        : bt_src(&t->GetExtension(ql2::extension::backtrace)) { }
    pb_rcheckable_t(const pb_rcheckable_t *rct) : bt_src(rct->bt_src) { }
    virtual void runtime_check(const char *test, const char *file, int line,
                               bool pred, std::string msg) const {
        ql::runtime_check(test, file, line, pred, msg, bt_src);
    }

    void rebase(const Term2 *t) {
        bt_src = &t->GetExtension(ql2::extension::backtrace);
    }

    // Propagate the associated backtrace through the rewrite term.
    void propagate(Term2 *t) const;
private:
    const Backtrace *bt_src;
};

// Use these macros to return errors to users.
#ifndef NDEBUG
#define rcheck_target(target, pred, msg) do {                                         \
        (pred)                                                                        \
        ? (target)->runtime_check(stringify(pred), __FILE__, __LINE__, true, (msg))   \
        : (target)->runtime_check(stringify(pred), __FILE__, __LINE__, false, (msg)); \
    } while (0)
#define rcheck_src(src, pred, msg) do {                                                \
        (pred)                                                                         \
        ? ql::runtime_check(stringify(pred), __FILE__, __LINE__, true, (msg), (src))   \
        : ql::runtime_check(stringify(pred), __FILE__, __LINE__, false, (msg), (src)); \
    } while (0)
#else
#define rcheck_target(target, pred, msg) do {                                         \
        (pred)                                                                        \
        ? (void)0                                                                     \
        : (target)->runtime_check(stringify(pred), __FILE__, __LINE__, false, (msg)); \
    } while (0)
#define rcheck_src(src, pred, msg) do {                                                \
        (pred)                                                                         \
        ? (void)0                                                                      \
        : ql::runtime_check(stringify(pred), __FILE__, __LINE__, false, (msg), (src)); \
    } while (0)
#endif // NDEBUG
#define rcheck(pred, msg) rcheck_target(this, pred, msg)
#define rcheck_toplevel(pred, msg) rcheck_src(0, pred, msg)

#define rfail_target(target, args...) rcheck_target(target, false, strprintf(args))
#define rfail(args...) rcheck(false, strprintf(args))
#define rfail_toplevel(args...) rcheck_toplevel(false, strprintf(args))


// r_sanity_check should be used in place of guarantee if you think the
// guarantee will almost always fail due to an error in the query logic rather
// than memory corruption.
#ifndef NDEBUG
#define r_sanity_check(test) guarantee(test)
#else
#define r_sanity_check(test) runtime_sanity_check(test)
#endif // NDEBUG

// A backtrace we return to the user.  Pretty self-explanatory.
class backtrace_t {
public:
    backtrace_t(const Backtrace *bt) {
        for (int i = 0; i < bt->frames_size(); ++i) {
            push_back(bt->frames(i));
        }
    }
    backtrace_t() { }

    class frame_t {
    public:
        explicit frame_t() : type(OPT), opt("UNITIALIZED") { }
        explicit frame_t(int32_t _pos) : type(POS), pos(_pos) { }
        explicit frame_t(const std::string &_opt) : type(OPT), opt(_opt) { }
        explicit frame_t(const char *_opt) : type(OPT), opt(_opt) { }
        explicit frame_t(const Frame &f);
        Frame toproto() const;

        static frame_t invalid() { return frame_t(INVALID); }
        bool is_invalid() const { return type == POS && pos == INVALID; }
        static frame_t head() { return frame_t(HEAD); }
        bool is_head() const { return type == POS && pos == HEAD; }
        static frame_t skip() { return frame_t(SKIP); }
        bool is_skip() const { return type == POS && pos == SKIP; }
        bool is_valid() { // -1 is the classic "invalid" frame
            return is_head() || is_skip()
                || (type == POS && pos >= 0)
                || (type == OPT && opt != "UNINITIALIZED");
        }
        bool is_stream_funcall_frame() {
            return type == POS && pos != 0;
        }
    private:
        enum special_frames {
            INVALID = -1,
            HEAD = -2,
            SKIP = -3
        };
        enum type_t { POS = 0, OPT = 1 };
        int32_t type; // serialize macros didn't like `type_t` for some reason
        int32_t pos;
        std::string opt;

    public:
        RDB_MAKE_ME_SERIALIZABLE_3(type, pos, opt);
    };

    void fill_bt(Backtrace *bt) const;
    // Write out the backtrace to return it to the user.
    void fill_error(Response2 *res, Response2_ResponseType type, std::string msg) const;
    RDB_MAKE_ME_SERIALIZABLE_1(frames);

    bool is_empty() { return frames.size() == 0; }

private:
    // Push a frame onto the back of the backtrace.
    void push_back(frame_t f) {
        r_sanity_check(f.is_valid());
        // debugf("PUSHING %s\n", f.toproto().DebugString().c_str());
        frames.push_back(f);
    }
    template<class T>
    void push_back(T t) {
        push_back(frame_t(t));
    }

    std::list<frame_t> frames;
};

const backtrace_t::frame_t head_frame = backtrace_t::frame_t::head();

// A RQL exception.  In the future it will be tagged.
class exc_t : public std::exception {
public:
    // We have a default constructor because these are serialized.
    exc_t() : exc_msg("UNINITIALIZED") { }
    // explicit exc_t(const std::string &_exc_msg) : exc_msg(_exc_msg) { }
    template<class T>
    exc_t(const std::string &_exc_msg, const T *bt_src)
        : exc_msg(_exc_msg) {
        if (bt_src) set_backtrace(bt_src);
    }
    exc_t(const std::string &_exc_msg, const backtrace_t &_backtrace)
        : backtrace(_backtrace), exc_msg(_exc_msg) { }
    virtual ~exc_t() throw () { }
    const char *what() const throw () { return exc_msg.c_str(); }
    RDB_MAKE_ME_SERIALIZABLE_2(backtrace, exc_msg);

    template<class T>
    void set_backtrace(const T *t) {
        r_sanity_check(backtrace.is_empty());
        backtrace = backtrace_t(t);
    }

    backtrace_t backtrace;
private:
    std::string exc_msg;
};

class datum_exc_t : public std::exception {
public:
    datum_exc_t(const std::string &_exc_msg) : exc_msg(_exc_msg) { }
    virtual ~datum_exc_t() throw () { }
    const char *what() const throw () { return exc_msg.c_str(); }
private:
    std::string exc_msg;
};

void fill_error(Response2 *res, Response2_ResponseType type, std::string msg,
                const backtrace_t &bt = backtrace_t());

} // namespace ql

#endif // RDB_PROTOCOL_ERR_HPP_
