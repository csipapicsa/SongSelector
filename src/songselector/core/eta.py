"""Remaining time of a long job (the embedding analysis) from its progress counts.

The speed is measured over a sliding window of recent progress (WINDOW seconds), not since the start: the first
tracks include loading the models, files that are missing finish at once, and the computer may get busier or
quieter while the job runs. Until MIN_DONE tracks have finished within at least MIN_SECONDS there is no estimate.
No Qt here (the UI formats and shows it).
"""
import math
import time
from collections import deque

WINDOW = 300.0      # seconds of recent progress the speed is taken from
MIN_DONE = 3        # finished items needed before estimating
MIN_SECONDS = 10.0  # ... over at least this long


class Eta:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.samples = deque()  # (time, done) whenever `done` changed

    def reset(self):
        """Forget the speed (the job was paused, or started again)."""
        self.samples.clear()

    def update(self, done, total):
        """Record progress; returns the estimated seconds left, or None while there is no estimate yet."""
        now = self.clock()
        if self.samples and done < self.samples[-1][1]:
            self.reset()  # counting started again
        if not self.samples or done != self.samples[-1][1]:
            self.samples.append((now, done))
        while len(self.samples) > 2 and now - self.samples[1][0] > WINDOW:
            self.samples.popleft()  # keep the window, but always two samples to measure between
        if done >= total or len(self.samples) < 2:
            return None
        (start, first), (_last_time, last) = self.samples[0], self.samples[-1]
        finished, seconds = last - first, now - start
        if finished < MIN_DONE or seconds < MIN_SECONDS:
            return None
        return (total - done) * seconds / finished


def format_left(seconds):
    """'about 3 h 25 min left', 'about 12 min left', 'less than a minute left'; '' for no estimate."""
    if seconds is None or not math.isfinite(seconds):
        return ''
    minutes = math.ceil(seconds / 60)
    if minutes <= 1:
        return 'less than a minute left'
    if minutes < 60:
        return f'about {minutes} min left'
    hours, minutes = divmod(minutes, 60)
    if hours >= 10:  # minutes are noise at that range
        return f'about {hours + (minutes >= 30)} h left'
    return f'about {hours} h {minutes} min left' if minutes else f'about {hours} h left'
