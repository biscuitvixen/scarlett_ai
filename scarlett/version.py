"""What this build is: a released version, and the commit behind it.

The two answer different questions and neither replaces the other. The
version is a deliberate claim about compatibility, bumped by hand in the
project metadata. The commit is provenance: which exact source produced
the container currently running, which is the thing worth knowing when
something misbehaves and the tag says only "latest".

The commit reaches the process as an environment variable baked in at
image build time, because the build context carries no git metadata.
Running from a checkout it is usually absent, which is the case where
the answer is already on screen.

Deliberately not on show: the version stays out of her status and her
profile, and is only answered when somebody asks.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version

# the version is read from the installed package rather than repeated here,
# so the one in the project metadata stays the only copy
PACKAGE = "scarlett"

UNKNOWN = "unknown"

# a short commit is enough to find the source and short enough to read out
SHA_LENGTH = 7


def package_version() -> str:
    try:
        return installed_version(PACKAGE)
    except PackageNotFoundError:
        # running from a source tree that was never installed
        return UNKNOWN


def short_sha(sha: str | None) -> str | None:
    """Trim a commit to something readable, None when there isn't one."""
    trimmed = (sha or "").strip()
    return trimmed[:SHA_LENGTH] if trimmed else None


def describe(version: str, sha: str | None = None) -> str:
    """`0.3.0 (1f65e17)`, or just the version when the commit is unknown."""
    trimmed = short_sha(sha)
    return f"{version} ({trimmed})" if trimmed else version
