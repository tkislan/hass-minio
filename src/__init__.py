import logging
import os
import threading
from queue import Queue

import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_START, EVENT_HOMEASSISTANT_STOP
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = ['minio==4.0.9']
_LOGGER = logging.getLogger(__name__)

DOMAIN = 'minio'
CONF_HOST = 'host'
CONF_PORT = 'port'
CONF_ACCESS_KEY = 'access_key'
CONF_SECRET_KEY = 'secret_key'
CONF_LISTEN = 'listen'
CONF_LISTEN_BUCKET = 'bucket'
CONF_LISTEN_PREFIX = 'prefix'
CONF_LISTEN_SUFFIX = 'suffix'
CONF_LISTEN_EVENTS = 'events'

CONF_LISTEN_PREFIX_DEFAULT = ''
CONF_LISTEN_SUFFIX_DEFAULT = '.*'
CONF_LISTEN_EVENTS_DEFAULT = 's3:ObjectCreated:*'

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT): cv.port,
        vol.Required(CONF_ACCESS_KEY): cv.string,
        vol.Required(CONF_SECRET_KEY): cv.string,
        vol.Optional(CONF_LISTEN): vol.All(cv.ensure_list, [vol.Schema({
            vol.Required(CONF_LISTEN_BUCKET): cv.string,
            vol.Optional(CONF_LISTEN_PREFIX, default=CONF_LISTEN_PREFIX_DEFAULT): cv.string,
            vol.Optional(CONF_LISTEN_SUFFIX, default=CONF_LISTEN_SUFFIX_DEFAULT): cv.string,
            vol.Optional(CONF_LISTEN_EVENTS, default=CONF_LISTEN_EVENTS_DEFAULT): cv.string,
        })])
    })
}, extra=vol.ALLOW_EXTRA)

SERVICE_GET_PUT_SCHEMA = vol.Schema({
    vol.Required('file_path'): cv.template,
    vol.Required('bucket'): cv.template,
    vol.Required('key'): cv.template,
})

SERVICE_REMOVE_SCHEMA = vol.Schema({
    vol.Required('bucket'): cv.template,
    vol.Required('key'): cv.template,
})


class QueueListener(threading.Thread):
    def __init__(self, hass):
        super().__init__()
        self.__hass = hass
        self.__q = Queue()

    def run(self):
        _LOGGER.info('Running QueueListener')
        while True:
            event = self.__q.get()
            if event is None:
                break

            _, file_name = os.path.split(event['key'])

            _LOGGER.info('Sending event %s, %s/%s, %s', event['event_name'], event['bucket'], event['key'])
            self.__hass.bus.fire(DOMAIN, {
                'file_name': file_name,
                **event,
            })

    @property
    def q(self):
        return self.__q

    def stop(self):
        _LOGGER.info('Stopping QueueListener')
        self.__q.put(None)
        self.join()
        _LOGGER.info('Stopped QueueListener')

    def start_handler(self, _):
        self.start()

    def stop_handler(self, _):
        self.stop()


class MinioListener:
    def __init__(self, *args):
        self.__args = args
        self.__minio_event_thread = None

    def start_handler(self, _):
        from .minio_helper import MinioEventThread

        self.__minio_event_thread = MinioEventThread(*self.__args)
        self.__minio_event_thread.start()

    def stop_handler(self, _):
        if self.__minio_event_thread is not None:
            self.__minio_event_thread.stop()


def setup(hass, config):
    conf = config[DOMAIN]

    host = conf[CONF_HOST]
    port = conf[CONF_PORT]
    access_key = conf[CONF_ACCESS_KEY]
    secret_key = conf[CONF_SECRET_KEY]

    queue_listener = QueueListener(hass)
    q = queue_listener.q

    hass.bus.listen_once(EVENT_HOMEASSISTANT_START, queue_listener.start_handler)
    hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, queue_listener.stop_handler)

    def _setup_listener(c):
        bucket = c[CONF_LISTEN_BUCKET]
        prefix = c[CONF_LISTEN_PREFIX]
        suffix = c[CONF_LISTEN_SUFFIX]
        events = c[CONF_LISTEN_EVENTS]

        minio_listener = MinioListener(q, f'{host}:{str(port)}', access_key, secret_key, bucket, prefix, suffix, events)

        hass.bus.listen_once(EVENT_HOMEASSISTANT_START, minio_listener.start_handler)
        hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, minio_listener.stop_handler)

    for listen_conf in conf.get(CONF_LISTEN, []):
        _setup_listener(listen_conf)

    from minio import Minio

    mc = Minio(f'{host}:{str(port)}', access_key, secret_key, secure=False)

    def _render_service_value(service, key):
        value = service.data.get(key)
        value.hass = hass
        return value.async_render()

    def put_file(service):
        bucket = _render_service_value(service, 'bucket')
        key = _render_service_value(service, 'key')
        file_path = _render_service_value(service, 'file_path')

        if not hass.config.is_allowed_path(file_path):
            _LOGGER.error('Invalid file_path %s', file_path)
            return

        mc.fput_object(bucket, key, file_path)

    def get_file(service):
        bucket = _render_service_value(service, 'bucket')
        key = _render_service_value(service, 'key')
        file_path = _render_service_value(service, 'file_path')

        if not hass.config.is_allowed_path(file_path):
            _LOGGER.error('Invalid file_path %s', file_path)
            return

        mc.fget_object(bucket, key, file_path)

    def remove_file(service):
        bucket = _render_service_value(service, 'bucket')
        key = _render_service_value(service, 'key')

        mc.remove_object(bucket, key)

    hass.services.register(DOMAIN, 'put', put_file, schema=SERVICE_GET_PUT_SCHEMA)
    hass.services.register(DOMAIN, 'get', get_file, schema=SERVICE_GET_PUT_SCHEMA)
    hass.services.register(DOMAIN, 'remove', remove_file, schema=SERVICE_REMOVE_SCHEMA)

    return True
