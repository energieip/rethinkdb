#!/usr/bin/env python
import sys

def generate_async_message_template(nargs):

    args = ", ".join("const arg%d_t &arg%d" % (i, i) for i in xrange(nargs))

    print "template<%s>" % ", ".join("class arg%d_t" % i for i in xrange(nargs))
    print "class async_mailbox_t< void(%s) > : private cluster_mailbox_t {" % \
        ", ".join("arg%d_t" % i for i in xrange(nargs))
    print
    print "public:"
    print "    async_mailbox_t(const boost::function< void(%s) > &fun) :" % args
    print "        callback(fun) { }"
    print
    print "    struct address_t {"
    print "        address_t() { }"
    print "        address_t(const address_t &other) : addr(other.addr) { }"
    print "        address_t(async_mailbox_t *mb) : addr(mb) { }"
    print "        void call(%s) {" % args
    if nargs > 0:
        print "            message_t m(%s);" % ", ".join("arg%d" % i for i in xrange(nargs));
    else:
        print "            message_t m;"
    print "            addr.send(&m);"
    print "        }"
    print "        RDB_MAKE_ME_SERIALIZABLE_1(address_t, addr)"
    # print "    private:"    # Make public temporarily
    print "        cluster_address_t addr;"
    print "    };"
    print "    friend class address_t;"
    print
    print "private:"
    print "    struct message_t : public cluster_message_t {"
    print "        message_t(%s)" % args
    if nargs > 0:
        print "            : %s { }" % ", ".join("arg%d(arg%d)" % (i,i) for i in xrange(nargs))
    else:
        print "            { }"
    for i in xrange(nargs):
        print "        const arg%d_t &arg%d;" % (i, i)
    print "        void serialize(cluster_outpipe_t *p) {"
    for i in xrange(nargs):
        print "            format_t<arg%d_t>::write(p, arg%d);" % (i,i)
    print "        }"
    print "        int ser_size() {"
    print "             int size = 0;"
    for i in xrange(nargs):
        print "            size += format_t<arg%d_t>::get_size(arg%d);" % (i, i)
    print "             return size;"
    print "        }"
    print "    };"
    print "#ifndef NDEBUG"
    print "     const std::type_info& expected_type() {"
    print "         return typeid(message_t);"
    print "     }"
    print "#endif"
    print "    void unserialize(cluster_inpipe_t *p) {"
    for i in xrange(nargs):
        print "        typename format_t<arg%d_t>::parser_t parser%d(p);" % (i,i)
    print "        p->done();"
    print "        callback(%s);" % ", ".join("parser%d.value()" % i for i in xrange(nargs))
    print "    }"
    print
    print "    boost::function< void(%s) > callback;" % args
    print "    void run(cluster_message_t *cm) {"
    if nargs:
        print "        message_t *m = static_cast<message_t *>(cm);"
    for i in xrange(nargs):
        # Copy each parameter from the message onto the stack because it might become invalid once
        # we call coro_t::wait(), and we would rather not make 'callback' worry about that.
        print "        arg%d_t arg%d(m->arg%d);" % (i, i, i)
    print "        callback(%s);" % ", ".join("arg%d" % i for i in xrange(nargs))
    print "    }"
    print "};"
    print

def generate_sync_message_template(nargs, void):

    args = ", ".join("const arg%d_t &arg%d" % (i, i) for i in xrange(nargs))
    ret = "ret_t" if not void else "void"

    if void:
        print "template<%s>" % ", ".join("class arg%d_t" % i for i in xrange(nargs))
    else:
        print "template<%s>" % ", ".join(["class ret_t"] + ["class arg%d_t" % i for i in xrange(nargs)])
    print "class sync_mailbox_t< %s(%s) > : private cluster_mailbox_t {" % \
        (ret, ", ".join("arg%d_t" % i for i in xrange(nargs)))
    print
    print "public:"
    print "    sync_mailbox_t(const boost::function< %s(%s) > &fun) :" % (ret, args)
    print "        callback(fun) { }"
    print
    print "    struct address_t {"
    print "        address_t() { }"
    print "        address_t(const address_t &other) : addr(other.addr) { }"
    print "        address_t(sync_mailbox_t *mb) : addr(mb) { }"
    print "        %s call(%s) {" % (ret, args)
    if nargs > 0:
        print "            call_message_t m(%s);" % ", ".join("arg%d" % i for i in xrange(nargs));
    else:
        print "            call_message_t m;"
    print "            struct : public cluster_mailbox_t, public %s, public cluster_peer_t::kill_cb_t {" % ("promise_t<std::pair<bool, ret_t> >" if not void else "promise_t<bool>")
    print "                void unserialize(cluster_inpipe_t *p) {"
    if not void:
        print "                    typename format_t<ret_t>::parser_t parser(p);"
        print "                    pulse(std::make_pair(true, parser.value()));"
    else:
        print "                    pulse(true);"
    print "                    p->done();"
    print "                }"
    print "                void run(cluster_message_t *msg) {"
    if not void:
        print "                    ret_message_t *m = static_cast<ret_message_t *>(msg);"
        print "                    pulse(std::make_pair(true, m->ret));"
    else:
        print "                    pulse(true);"
    print "                }"
    print "#ifndef NDEBUG"
    print "                const std::type_info& expected_type() {"
    print "                    return typeid(ret_message_t);"
    print "                }"
    print "#endif"
    print "                void on_kill() {"
    if not void:
        print "                    pulse(std::make_pair(false, ret_t()));"
    else:
        print "                    pulse(false);"
    print "                }"
    print "            } reply_listener;"
    print "            m.reply_to = cluster_address_t(&reply_listener);"
    print "            cluster_t::peer_kill_monitor_t monitor(addr.get_peer(), &reply_listener);"
    print "            addr.send(&m);"
    if not void:
        print "            std::pair<bool, ret_t> res = reply_listener.wait();"
        print "            if (res.first) return res.second;"
        print "            else throw rpc_peer_killed_exc_t();"
    else:
        print "            if (!reply_listener.wait()) throw rpc_peer_killed_exc_t();"
    print "        }"
    print "        RDB_MAKE_ME_SERIALIZABLE_1(address_t, addr)"
    print "    private:"
    print "        cluster_address_t addr;"
    print "    };"
    print "    friend class address_t;"
    print
    print "private:"
    print "    struct call_message_t : public cluster_message_t {"
    print "        call_message_t(%s)" % args
    if nargs > 0:
        print "            : %s { }" % ", ".join("arg%d(arg%d)" % (i,i) for i in xrange(nargs))
    else:
        print "            { }"
    for i in xrange(nargs):
        print "        const arg%d_t &arg%d;" % (i, i)
    print "        cluster_address_t reply_to;"
    print "        void serialize(cluster_outpipe_t *p) {"
    for i in xrange(nargs):
        print "            format_t<arg%d_t>::write(p, arg%d);" % (i, i)
    print "            format_t<cluster_address_t>::write(p, reply_to);"
    print "        }"
    print "        int ser_size() {"
    print "             int size = 0;"
    for i in xrange(nargs):
        print "             size += format_t<arg%d_t>::get_size(arg%d);" % (i, i)
    print "             size += format_t<cluster_address_t>::get_size(reply_to);"
    print "             return size;"
    print "        }"
    print "    };"
    print "#ifndef NDEBUG"
    print "     const std::type_info& expected_type() {"
    print "         return typeid(call_message_t);"
    print "     }"
    print "#endif"
    print
    print "    struct ret_message_t : public cluster_message_t {"
    if not void:
        print "        ret_t ret;"
    print "        void serialize(cluster_outpipe_t *p) {"
    if not void:
        print "            format_t<ret_t>::write(p, ret);"
    print "        }"
    print "        int ser_size() {"
    if not void:
        print "             return format_t<ret_t>::get_size(ret);"
    else:
        print "             return 0;"
    print "        }"
    print "    };"
    print
    print "    boost::function< %s(%s) > callback;" % (ret, args)
    print
    print "    void unserialize(cluster_inpipe_t *p) {"
    for i in xrange(nargs):
        print "        typename format_t<arg%d_t>::parser_t parser%d(p);" % (i, i)
    print "        format_t<cluster_address_t>::parser_t reply_parser(p);"
    print "        p->done();"
    print "        ret_message_t rm;"
    if not void:
        print "        rm.ret = callback(%s);" % ", ".join("parser%d.value()" % i for i in xrange(nargs))
    else:
        print "        callback(%s);" % ", ".join("parser%d.value()" % i for i in xrange(nargs))
    print "        reply_parser.value().send(&rm);"
    print "    }"
    print
    print "    void run(cluster_message_t *cm) {"
    print "        call_message_t *m = static_cast<call_message_t *>(cm);"
    print "        ret_message_t rm;"
    if not void:
        print "        rm.ret = callback(%s);" % ", ".join("m->arg%d" % i for i in xrange(nargs))
    else:
        print "        callback(%s);" % ", ".join("m->arg%d" % i for i in xrange(nargs))
    print "        m->reply_to.send(&rm);"
    print "    }"
    print "};"
    print

if __name__ == "__main__":

    print "#ifndef __CLUSTERING_RPC_HPP__"
    print "#define __CLUSTERING_RPC_HPP__"
    print

    print "/* This file is automatically generated by '%s'." % " ".join(sys.argv)
    print "Please modify '%s' instead of modifying this file.*/" % sys.argv[0]
    print

    print "#include \"clustering/serialize.hpp\""
    print "#include \"clustering/serialize_macros.hpp\""
    print "#include \"concurrency/cond_var.hpp\""
    print "#include \"clustering/cluster.hpp\""
    print "#include \"clustering/peer.hpp\""
    print

    print "template<class proto_t> class async_mailbox_t {"
    print "    // BOOST_STATIC_ASSERT(false);"
    print "};"
    print
    print "template<class proto_t> class sync_mailbox_t;"
    print
    print "struct rpc_peer_killed_exc_t : public std::exception {"
    print "    const char *what() throw () {"
    print "        return \"Peer killed during rpc\\n\";"
    print "    }"
    print "};"

    for nargs in xrange(10):
        generate_async_message_template(nargs)
        generate_sync_message_template(nargs, True);
        generate_sync_message_template(nargs, False);

    print
    print "#endif /* __CLUSTERING_RPC_HPP__ */"
