import time
import os

from watchdog.events import FileModifiedEvent

from minio_bridge import Watcher, DebounceHandler


def _handle_event(event: FileModifiedEvent):
    print(event.src_path)


if __name__ == '__main__':
    os.makedirs('/root/data', exist_ok=True)

    with DebounceHandler(_handle_event) as handle_event:
        with Watcher(handle_event, '/root/data'):
            print('Running')

            with open('/root/data/test', 'w') as f:
                for i in range(30):
                    f.write('hello\n' * 500)
                    time.sleep(0.2)

            time.sleep(2)

    # with Watcher(handle_event, '/root/data'):
    #     print('Running')
    #
    #     with open('/root/data/test', 'w') as f:
    #         for i in range(10):
    #             f.write('hello\n')
    #             time.sleep(2)
