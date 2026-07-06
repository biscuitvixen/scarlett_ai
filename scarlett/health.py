"""Liveness heartbeat shared by the bot and the container healthcheck.

The bot has no HTTP surface, so "is it healthy" really means "is she still
connected to the gateway and is the event loop still turning". The Health cog
(scarlett.cogs.health) stamps the current time into HEARTBEAT_PATH every
HEARTBEAT_INTERVAL seconds while the bot is ready; Docker's HEALTHCHECK runs
`python -m scarlett.health`, which exits non-zero once that stamp goes stale.

Kept dependency-free on purpose so the healthcheck process starts fast and
doesn't drag discord.py in just to read one file.
"""

import sys
import time
from pathlib import Path

# ephemeral by design: a fresh container has no heartbeat and only reads
# healthy once she connects, and a crash leaves the last stamp to go stale
# rather than lingering across restarts the way a file on the data volume would
HEARTBEAT_PATH = Path("/tmp/scarlett.heartbeat")
HEARTBEAT_INTERVAL = 30.0
# three missed beats. loose enough to ride out discord.py resuming a dropped
# session on its own without the check flapping to unhealthy
MAX_STALENESS = 90.0


def write_heartbeat(path: Path = HEARTBEAT_PATH) -> None:
    path.write_text(str(time.time()))


def check(path: Path = HEARTBEAT_PATH, now: float | None = None) -> str | None:
    """None if the last heartbeat is fresh, else a human reason it isn't."""
    if now is None:
        now = time.time()
    try:
        beat = float(path.read_text())
    except (OSError, ValueError):
        return "no heartbeat yet"
    age = now - beat
    if age > MAX_STALENESS:
        return f"heartbeat stale ({age:.0f}s old)"
    return None


def main() -> None:
    reason = check()
    if reason is not None:
        print(reason)
        sys.exit(1)
    print("ok")


if __name__ == "__main__":
    main()
