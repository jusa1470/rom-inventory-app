import threading
import time


class AdaptiveLimiter:
    def __init__(self, start=4, lo=1, hi=12, grow_after=20):
        self.limit, self.lo, self.hi, self.grow_after = start, lo, hi, grow_after
        self.active = 0
        self.ok = 0
        self._cool_until = 0.0
        self._cv = threading.Condition()

    def __enter__(self):
        with self._cv:
            while self.active >= self.limit:
                self._cv.wait()
            self.active += 1
        wait = self._cool_until - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def __exit__(self, *exc):
        with self._cv:
            self.active -= 1
            self._cv.notify_all()

    def success(self):
        with self._cv:
            self.ok += 1
            if self.ok >= self.grow_after and self.limit < self.hi:
                self.limit += 1
                self.ok = 0
                self._cv.notify_all()

    def throttled(self, retry_after=0):
        with self._cv:
            self.limit = max(self.lo, self.limit // 2)
            self.ok = 0
            self._cool_until = max(self._cool_until, time.monotonic() + max(retry_after, 2))