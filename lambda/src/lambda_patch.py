"""Lambda-compatible patch for Bittensor SDK.

The Bittensor SDK's logging system uses multiprocessing.Queue which requires
/dev/shm (shared memory). Lambda doesn't provide /dev/shm, so we patch
multiprocessing to use a thread-safe queue instead.

This module MUST be imported before `bittensor` in any Lambda handler.
"""

import multiprocessing
import queue


class _FakeQueue:
    """Drop-in replacement for multiprocessing.Queue using a thread-safe queue."""

    def __init__(self, maxsize=-1, **kwargs):
        self._queue = queue.Queue(maxsize=0 if maxsize == -1 else maxsize)

    def put(self, obj, block=True, timeout=None):
        self._queue.put(obj, block=block, timeout=timeout)

    def put_nowait(self, obj):
        self._queue.put_nowait(obj)

    def get(self, block=True, timeout=None):
        return self._queue.get(block=block, timeout=timeout)

    def get_nowait(self):
        return self._queue.get_nowait()

    def empty(self):
        return self._queue.empty()

    def qsize(self):
        return self._queue.qsize()

    def close(self):
        pass

    def join_thread(self):
        pass


# Monkey-patch multiprocessing.Queue before bittensor imports it
multiprocessing.Queue = _FakeQueue
