import threading
import time


class AdaptiveLimiter:
    def __init__(
        self,
        start=4,
        lo=1,
        hi=12,
        sample_seconds=10,
        min_sample_requests=20,
        improvement=0.05,
    ):
        self.limit = self.lo = lo
        self.hi = hi

        self.limit = max(lo, min(start, hi))

        self.sample_seconds = sample_seconds
        self.min_sample_requests = min_sample_requests
        self.improvement = improvement

        self.active = 0
        self._cool_until = 0.0
        self._cv = threading.Condition()

        # Throughput measurement
        self._window_start = time.monotonic()
        self._window_requests = 0

        # Best-performing worker count
        self._best_limit = self.limit
        self._best_rate = 0.0

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

    def _reset_window(self, now):
        self._window_start = now
        self._window_requests = 0

    def success(self, elapsed=None):
        with self._cv:
            now = time.monotonic()
            self._window_requests += 1

            duration = now - self._window_start

            if duration < self.sample_seconds:
                return

            if (
                self._window_requests < self.min_sample_requests
                and duration < self.sample_seconds * 3
            ):
                return

            rate = self._window_requests / duration

            # Establish initial baseline
            if self._best_rate == 0:
                self._best_rate = rate
                self._best_limit = self.limit

            elif self.limit > self._best_limit:
                # Evaluate a higher worker count
                if rate > self._best_rate * (1 + self.improvement):
                    # Higher concurrency is faster: keep it
                    self._best_limit = self.limit
                    self._best_rate = rate
                else:
                    # Higher concurrency didn't improve throughput
                    self.limit = self._best_limit
                    self._cool_until = now + 2
                    self._cv.notify_all()

            elif self.limit == self._best_limit:
                # Update baseline performance
                self._best_rate = (
                    0.8 * self._best_rate + 0.2 * rate
                )

            self._reset_window(now)

            # Probe one worker higher
            if self.limit == self._best_limit and self.limit < self.hi:
                self.limit += 1
                self._cv.notify_all()

    def throttled(self, retry_after=0):
        with self._cv:
            self.limit = max(self.lo, self.limit // 2)

            # Relearn the optimum after throttling
            self._best_limit = self.limit
            self._best_rate = 0.0

            self._reset_window(time.monotonic())

            self._cool_until = max(
                self._cool_until,
                time.monotonic() + max(retry_after, 2)
            )

            self._cv.notify_all()
