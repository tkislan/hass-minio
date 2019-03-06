from typing import List, Callable, Any
import asyncio
import threading

from watchdog.events import PatternMatchingEventHandler, FileModifiedEvent
from watchdog.observers import Observer


class MinioBridge:
    def __init__(self, configs):
        pass


class DebounceHandler(threading.Thread):
    def __init__(self, callback: Callable[[Any], None], timeout: int = 1):
        super().__init__()
        self.__callback = callback
        self.__timeout = timeout
        self.__loop = asyncio.new_event_loop()
        self.__scheduled_calls = {}

    def __enter__(self):
        self.start()
        return self.handle_event

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def run(self):
        try:
            self.__loop.run_forever()
        finally:
            self.__loop.close()

    def handle_event(self, event: Any):
        self.__loop.call_soon_threadsafe(self._schedule_callback, event)

    def _schedule_callback(self, event: Any):
        if event in self.__scheduled_calls:
            self.__scheduled_calls[event].cancel()

        self.__scheduled_calls[event] = self.__loop.call_later(self.__timeout, lambda: self._call_callback(event))

    def _call_callback(self, src_path: str):
        self.__scheduled_calls.pop(src_path, None)
        self.__callback(src_path)

    def stop(self):
        self.__loop.call_soon_threadsafe(self.__loop.stop)
        self.join()


def create_event_handler(patterns: List[str], callback: Callable[[FileModifiedEvent], None]):
    class EventHandler(PatternMatchingEventHandler):
        def __init__(self):
            super().__init__(patterns=patterns, ignore_directories=True)

        def on_modified(self, event: FileModifiedEvent):
            callback(event)

    return EventHandler()


class Watcher:
    def __init__(self, callback: Callable[[Any], None], path: str, patterns: List[str] = None):
        self.__observer = Observer()
        self.__observer.schedule(
            create_event_handler(patterns or ['*'], callback),
            path,
            recursive=True
        )

    def __enter__(self):
        self.start()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start(self):
        self.__observer.start()

    def stop(self):
        self.__observer.stop()
        self.__observer.join()


class WatcherGroup:
    def __init__(self, callback: Callable[[Any], None]):
        self.__watchers = []
        self.__callback = callback
        self.__debounce_handler = DebounceHandler(self.__callback)
        self.__debounce_handler.start()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def add(self, *args, **kwargs):
        watcher = Watcher(self.__debounce_handler.handle_event, *args, **kwargs)
        self.__watchers.append(watcher)
        watcher.start()

    def stop(self):
        for watcher in self.__watchers:
            watcher.stop()
        self.__debounce_handler.stop()
