#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging

from cow.server import Server
from cow.plugins.sqlalchemy_plugin import SQLAlchemyPlugin
from cow.plugins.redis_plugin import RedisPlugin, CowRedisClient
from tornado.httpclient import AsyncHTTPClient
#from toredis import Client
import redis
from materialgirl import Materializer
from materialgirl.storage.redis import RedisStorage
import tornado

from holmes.handlers.worker import WorkerHandler, WorkersHandler, WorkersInfoHandler
from holmes.handlers.worker_state import WorkerStateHandler
from holmes.handlers.page import (
    PageHandler, PageReviewsHandler, PageViolationsPerDayHandler, NextJobHandler
)
from holmes.handlers.violation import (
    MostCommonViolationsHandler, ViolationsHandler, ViolationHandler, ViolationDomainsHandler
)
from holmes.handlers.review import (
    ReviewHandler, LastReviewsHandler
)
from holmes.handlers.domains import (
    DomainsHandler, DomainDetailsHandler, DomainViolationsPerDayHandler,
    DomainReviewsHandler, DomainsChangeStatusHandler, DomainsFullDataHandler,
    DomainPageCountHandler, DomainReviewCountHandler, DomainViolationCountHandler,
    DomainErrorPercentageHandler, DomainResponseTimeAvgHandler, DomainGroupedViolationsHandler,
    DomainTopCategoryViolationsHandler
)
from holmes.handlers.search import (
    SearchHandler
)
from holmes.handlers.settings import (
    TaxHandler
)
from holmes.handlers.request import RequestDomainHandler, LastRequestsHandler
from holmes.handlers.limiter import LimiterHandler

from holmes.handlers.bus import EventBusHandler
from holmes.event_bus import EventBus, NoOpEventBus
from holmes.utils import load_classes
from holmes.models import Key
from holmes.models import KeysCategory
from holmes.cache import Cache
from holmes import __version__


def main():
    AsyncHTTPClient.configure("tornado.curl_httpclient.CurlAsyncHTTPClient")
    HolmesApiServer.run()


class VersionHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(__version__)


class HolmesApiServer(Server):
    def __init__(self, db=None, debug=None, *args, **kw):
        super(HolmesApiServer, self).__init__(*args, **kw)

        self.force_debug = debug
        self.db = db

    def get_extra_server_parameters(self):
        return {
            'no_keep_alive': False
        }

    def initialize_app(self, *args, **kw):
        super(HolmesApiServer, self).initialize_app(*args, **kw)

        self.application.db = None

        if self.force_debug is not None:
            self.debug = self.force_debug

    def get_handlers(self):
        handlers = [
            (r'/most-common-violations/?', MostCommonViolationsHandler),
            (r'/last-reviews/?', LastReviewsHandler),
            (r'/workers/?', WorkersHandler),
            (r'/workers/info/?', WorkersInfoHandler),
            (r'/worker/([a-z0-9-]*)/(alive|dead)/?', WorkerHandler),
            (r'/worker/([a-z0-9-]*)/(start|complete)/?', WorkerStateHandler),
            (r'/page/([a-z0-9-]*)/review/([a-z0-9-]*)/?', ReviewHandler),
            (r'/page/([a-z0-9-]*)/reviews/?', PageReviewsHandler),
            (r'/page/([a-z0-9-]*)/violations-per-day/?', PageViolationsPerDayHandler),
            (r'/page/([a-z0-9-]*)/?', PageHandler),
            (r'/search/?', SearchHandler),
            (r'/page/?', PageHandler),
            (r'/domains/?', DomainsHandler),
            (r'/domains-details/?', DomainsFullDataHandler),
            (r'/domains/([^/]+)/?', DomainDetailsHandler),
            (r'/domains/([^/]+)/page-count/?', DomainPageCountHandler),
            (r'/domains/([^/]+)/review-count/?', DomainReviewCountHandler),
            (r'/domains/([^/]+)/violation-count/?', DomainViolationCountHandler),
            (r'/domains/([^/]+)/error-percentage/?', DomainErrorPercentageHandler),
            (r'/domains/([^/]+)/response-time-avg/?', DomainResponseTimeAvgHandler),
            (r'/domains/([^/]+)/violations-per-day/?', DomainViolationsPerDayHandler),
            (r'/domains/([^/]+)/violations/?', DomainGroupedViolationsHandler),
            (r'/domains/([^/]+)/violations/([0-9]+)/?', DomainTopCategoryViolationsHandler),
            (r'/domains/([^/]+)/reviews/?', DomainReviewsHandler),
            (r'/domains/([^/]+)/change-status/?', DomainsChangeStatusHandler),
            (r'/domains/([^/]+)/requests/([0-9]*)/?', RequestDomainHandler),
            #(r'/events/?', EventBusHandler),
            (r'/violations/?', ViolationsHandler),
            (r'/violation/([_a-z0-9\.]*)/?', ViolationHandler),
            (r'/violation/([_a-z0-9\.]*)/domains/?', ViolationDomainsHandler),
            (r'/tax/?', TaxHandler),
            (r'/limiters/?', LimiterHandler),
            (r'/next-jobs/?', NextJobHandler),
            (r'/last-requests/?', LastRequestsHandler),
            (r'/version/?', VersionHandler),
        ]

        return tuple(handlers)

    def get_plugins(self):
        return [
            SQLAlchemyPlugin,
            RedisPlugin
        ]

    def after_start(self, io_loop):
        if self.db is not None:
            self.application.db = self.db
        else:
            self.application.db = self.application.get_sqlalchemy_session()

        if self.debug:
            from sqltap import sqltap
            self.sqltap = sqltap.start()

        self.application.facters = self._load_facters()
        self.application.validators = self._load_validators()
        self.application.error_handlers = [handler(self.application.config) for handler in self._load_error_handlers()]

        self.application.fact_definitions = {}
        self.application.violation_definitions = {}

        for facter in self.application.facters:
            self.application.fact_definitions.update(facter.get_fact_definitions())

        self._insert_keys(self.application.fact_definitions)

        for validator in self.application.validators:
            self.application.violation_definitions.update(validator.get_violation_definitions())

        self._insert_keys(self.application.violation_definitions)

        self.application.event_bus = NoOpEventBus(self.application)
        self.application.http_client = AsyncHTTPClient(io_loop=io_loop)
        self.connect_pub_sub(io_loop)

        self.application.cache = Cache(self.application)

        #self.configure_material_girl()

    def configure_material_girl(self):
        from holmes.material import configure_materials

        host = self.config.get('MATERIAL_GIRL_REDISHOST')
        port = self.config.get('MATERIAL_GIRL_REDISPORT')

        self.redis_material = redis.StrictRedis(host=host, port=port, db=0)

        self.application.girl = Materializer(storage=RedisStorage(redis=self.redis_material))

        configure_materials(self.application.girl, self.application.db, self.config)

    def _insert_key_category(self, key, name):
        category = KeysCategory.get_or_create(self.application.db, name)
        self.application.db.add(category)
        self.application.db.flush()
        self.application.db.commit()
        return category

    def _insert_keys(self, keys):
        for name in keys.keys():
            key = Key.get_or_create(self.application.db, name)
            keys[name]['key'] = key

            category_name = keys[name].get('category', None)
            if category_name:
                category = self._insert_key_category(key, category_name)
                key.category = category

            self.application.db.add(key)
            self.application.db.flush()
            self.application.db.commit()

    def _load_validators(self):
        return load_classes(default=self.config.VALIDATORS)

    def _load_facters(self):
        return load_classes(default=self.config.FACTERS)

    def _load_error_handlers(self):
        return load_classes(default=self.config.ERROR_HANDLERS)

    def before_end(self, io_loop):
        self.application.db.remove()

        if self.debug and getattr(self, 'sqltap', None) is not None:
            from sqltap import sqltap

            statistics = self.sqltap.collect()
            sqltap.report(statistics, "report.html")

    def connect_pub_sub(self, io_loop):
        host = self.application.config.get('REDISHOST')
        port = self.application.config.get('REDISPORT')

        logging.info("Connecting pubsub to redis at %s:%d" % (host, port))

        self.application.redis_pub_sub = CowRedisClient(io_loop=io_loop)
        self.application.redis_pub_sub.authenticated = False
        self.application.redis_pub_sub.connect(host, port, callback=self.has_connected(self.application))

    def has_connected(self, application):
        def handle(*args, **kw):
            password = application.config.get('REDISPASS', None)
            if password:
                application.redis_pub_sub.auth(password, callback=self.handle_authenticated(application))
            else:
                self.handle_authenticated(application)()
        return handle

    def handle_authenticated(self, application):
        def handle(*args, **kw):
            application.redis_pub_sub.authenticated = True
            application.event_bus = EventBus(self.application)  # can now connect to redis using pubsub

        return handle

if __name__ == '__main__':
    main()
