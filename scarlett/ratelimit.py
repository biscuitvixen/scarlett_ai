"""Per-user throttling for Scarlett's chat.

The cooldown between replies escalates the more someone talks to her, and
heals back down when they go quiet. A few back to back messages sit at the
base gap; past that each reply multiplies the required gap, so a persistent
one-person conversation gets slower and slower rather than cut off dead. A
rolling one hour cap is the hard ceiling on top.

Each person carries a "level" that rises by one per reply and decays by one
every `recover` seconds of silence. The required gap is
`base * factor ** (level - burst)`, floored at `base` and capped at
`max_cooldown`.

Kept as a plain in-memory helper (state resets on restart, which is fine) so
the logic can be unit tested without Discord. Owner exemption is the caller's
job, so this class stays generic.
"""

from collections import defaultdict, deque

HOUR = 3600.0


class RateLimiter:
    def __init__(
        self,
        base: float,
        burst: int,
        factor: float,
        max_cooldown: float,
        recover: float,
        hourly_cap: int,
    ):
        self.base = base
        self.burst = burst
        self.factor = factor
        self.max_cooldown = max_cooldown
        self.recover = recover
        self.hourly_cap = hourly_cap
        self.level: dict[int, float] = {}
        self.last: dict[int, float] = {}
        self.hits: dict[int, deque[float]] = defaultdict(deque)

    def allowed(self, user_id: int, now: float) -> bool:
        last = self.last.get(user_id)
        if last is not None:
            gap = self._cooldown(self._level(user_id, now))
            if now - last < gap:
                return False
        self._prune(user_id, now)
        return len(self.hits[user_id]) < self.hourly_cap

    def record(self, user_id: int, now: float) -> None:
        self.level[user_id] = self._level(user_id, now) + 1.0
        self.last[user_id] = now
        self._prune(user_id, now)
        self.hits[user_id].append(now)

    def _level(self, user_id: int, now: float) -> float:
        # the stored level decayed by however long they've been quiet
        last = self.last.get(user_id)
        if last is None:
            return 0.0
        decayed = self.level.get(user_id, 0.0) - (now - last) / self.recover
        return max(0.0, decayed)

    def _cooldown(self, level: float) -> float:
        extra = max(0.0, level - self.burst)
        return min(self.max_cooldown, self.base * self.factor**extra)

    def _prune(self, user_id: int, now: float) -> None:
        hits = self.hits[user_id]
        while hits and now - hits[0] >= HOUR:
            hits.popleft()
