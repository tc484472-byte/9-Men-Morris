import time


class Animator:
    """Remembers the point that was just played so the UI can animate it."""

    def __init__(self):
        self.highlight_until = 0
        self.position = None
        self.start = 0
        self.duration = 0.7

    def highlight(self, position, duration=0.7):
        self.position = position
        self.start = time.time()
        self.duration = duration
        self.highlight_until = self.start + duration

    def active(self):
        return self.position is not None and time.time() < self.highlight_until

    def age(self):
        """Seconds since the last highlight, or None when it has finished."""
        if not self.active():
            return None
        return time.time() - self.start
