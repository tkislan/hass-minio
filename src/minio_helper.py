import collections
import json
import logging
import re
import threading
from queue import Queue
from typing import Iterator, List
from urllib.parse import unquote

from minio import Minio

_LOGGER = logging.getLogger(__name__)


_METADATA_RE = re.compile('x-amz-meta-(.*)', re.IGNORECASE)


def normalize_metadata(metadata: dict) -> dict:
    new_metadata = {}
    for meta_key in metadata.keys():
        m = _METADATA_RE.match(meta_key)
        if not m:
            continue

        new_metadata[m.group(1).lower()] = metadata[meta_key]

    return new_metadata


def get_minio_notification_response(mc, bucket_name: str, prefix: str, suffix: str, events: List[str]):
    query = {
        'prefix': prefix,
        'suffix': suffix,
        'events': events,
    }
    # noinspection PyProtectedMember
    return mc._url_open('GET', bucket_name=bucket_name, query=query, preload_content=False)


class MinioEventStreamIterator(collections.Iterable):
    def __iter__(self) -> Iterator:
        return self

    def __init__(self, response):
        self.__response = response
        self.__stream = response.stream()

    def __next__(self):
        while True:
            line = next(self.__stream)
            if line.strip():
                event = json.loads(line.decode('utf-8'))
                if event['Records'] is not None:
                    return event

    def close(self):
        self.__response.close()


class MinioEventThread(threading.Thread):
    def __init__(self, q: Queue, endpoint: str, access_key: str, secret_key: str, bucket_name: str, prefix: str, suffix: str, events: List[str]):
        super().__init__()
        self.__q = q
        self.__endpoint = endpoint
        self.__access_key = access_key
        self.__secret_key = secret_key
        self.__bucket_name = bucket_name
        self.__prefix = prefix
        self.__suffix = suffix
        self.__events = events
        self.__event_stream_it = None

    def __enter__(self):
        self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def run(self):
        _LOGGER.info('Running MinioEventThread')

        mc = Minio(self.__endpoint, self.__access_key, self.__secret_key, secure=False)

        while True:
            _LOGGER.info('Connecting to minio event stream')
            response = get_minio_notification_response(mc, self.__bucket_name, self.__prefix, self.__suffix, self.__events)
            self.__event_stream_it = MinioEventStreamIterator(response)

            try:
                for event in self.__event_stream_it:
                    for event_name, bucket, key, metadata in iterate_objects(event):
                        self.__q.put({
                            "event_name": event_name,
                            "bucket": bucket,
                            "key": key,
                            "metadata": metadata,
                        })
            except json.JSONDecodeError:
                response.close()
            except AttributeError:
                break

    def stop(self):
        _LOGGER.info('Stopping event thread')
        if self.__event_stream_it is not None:
            self.__event_stream_it.close()
            self.__event_stream_it = None

        _LOGGER.info('Joining event thread')
        self.join()
        _LOGGER.info('Event thread joined')


def iterate_objects(event):
    records = event.get('Records', [])

    for record in records:
        event_name = record.get('eventName')
        bucket = record.get('s3', {}).get('bucket', {}).get('name')
        key = record.get('s3', {}).get('object', {}).get('key')
        metadata = normalize_metadata(record.get('s3', {}).get('object', {}).get('userMetadata', {}))

        if not bucket or not key:
            _LOGGER.info('Invalid bucket and/or key', bucket, key)
            continue

        key = unquote(key)

        yield event_name, bucket, key, metadata
