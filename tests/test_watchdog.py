import os
import tempfile
import unittest
import time
import shutil

from minio_bridge import WatcherGroup


class TemporaryDirectory:
    def __enter__(self):
        self.__dir_path = tempfile.mkdtemp()
        return self.__dir_path

    def __exit__(self, exc_type, exc_val, exc_tb):
        shutil.rmtree(self.__dir_path)


class WatchdogTest(unittest.TestCase):

    def setUp(self):
        self.event_time = None

    def handle_event(self, _):
        self.assertIsNone(self.event_time)
        self.event_time = int(time.time())

    def test_watchdog(self):
        with TemporaryDirectory() as tmp_dir_path:
            with WatcherGroup(self.handle_event) as watcher_group:
                watcher_group.add(path=tmp_dir_path)
                with open(os.path.join(tmp_dir_path, 'test'), 'w') as f:
                    for i in range(30):
                        f.write('hello\n' * 500)
                        time.sleep(0.2)

                file_closed_time = int(time.time())

                time.sleep(2)

            self.assertIsNotNone(file_closed_time)
            self.assertIsNotNone(self.event_time)
            self.assertLess(file_closed_time, self.event_time)
