"""Per-user throttling for Scarlett's chat.

Two limits per person: a short cooldown between replies, and a rolling one
hour cap. Kept as a plain in-memory helper (state resets on restart, which is
fine) so the logic can be unit tested without Discord. Owner exemption is the
caller's job, so this class stays generic.
"""

from collections import defaultdict, deque

HOUR = 3600.0


class RateLimiter:
    def __init__(self, cooldown: float, hourly_cap: int):
        self.cooldown = cooldown
        self.hourly_cap = hourly_cap
        self.last: dict[int, float] = {}
        self.hits: dict[int, deque[float]] = defaultdict(deque)

    def allowed(self, user_id: int, now: float) -> bool:
        last = self.last.get(user_id)
        if last is not None and now - last < self.cooldown:
            return False
        self._prune(user_id, now)
        return len(self.hits[user_id]) < self.hourly_cap

    def record(self, user_id: int, now: float) -> None:
        self.last[user_id] = now
        self._prune(user_id, now)
        self.hits[user_id].append(now)

    def _prune(self, user_id: int, now: float) -> None:
        hits = self.hits[user_id]
        while hits and now - hits[0] >= HOUR:
            hits.popleft()
