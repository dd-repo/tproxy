# -*- coding: utf-8 -
#
# This file is part of tproxy released under the MIT license. 
# See the NOTICE for more information.

import os
import logging
import signal

import gevent
from gevent.pool import Pool

from . import util
from .proxy import ProxyServer
from .workertmp import WorkerTmp

class Worker(ProxyServer):

    SIGNALS = map(
        lambda x: getattr(signal, "SIG%s" % x),
        "HUP QUIT INT TERM USR1 USR2 WINCH CHLD".split()
    )

    def __init__(self, age, ppid, listener, cfg, script):
        ProxyServer.__init__(self, listener, script, 
                spawn=Pool(cfg.worker_connections))
        self.age = age
        self.ppid = ppid
        self.cfg = cfg
        self.tmp = WorkerTmp(cfg)
        self.booted = False
        self.log = logging.getLogger(__name__)

    def __str__(self):
        return "<Worker %s>" % self.pid

    @property
    def pid(self):
        return os.getpid()

    def init_process(self):
        #gevent doesn't reinitialize dns for us after forking
        #here's the workaround
        gevent.core.dns_shutdown(fail_requests=1)
        gevent.core.dns_init()

        util.set_owner_process(self.cfg.uid, self.cfg.gid)

        # Reseed the random number generator
        util.seed()

        # Prevent fd inherientence
        util.close_on_exec(self.socket)
        util.close_on_exec(self.tmp.fileno())

        map(lambda s: signal.signal(s, signal.SIG_DFL), self.SIGNALS)
        self.booted = True

    def start_heartbeat(self):
        def notify():
            while self.started:
                gevent.sleep(self.cfg.timeout / 2.0)

                # If our parent changed then we shut down.
                if self.ppid != os.getppid():
                    self.log.info("Parent changed, shutting down: %s" % self)
                    return

                self.tmp.notify()

        return gevent.spawn(notify)

    def serve_forever(self):
        self.init_process()
        self.start_heartbeat()
        super(Worker, self).serve_forever()

    def kill(self):
        """stop accepting."""
        self.started = False
        try:
            self.stop_accepting()
        finally:
            self.__dict__.pop('socket', None)
            self.__dict__.pop('handle', None)
