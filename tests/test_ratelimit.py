from scarlett.ratelimit import RateLimiter

ALICE = 1
BOB = 2


def test_cooldown_blocks_then_clears():
    rl = RateLimiter(cooldown=10, hourly_cap=100)
    assert rl.allowed(ALICE, now=0)
    rl.record(ALICE, now=0)
    # inside the cooldown window
    assert not rl.allowed(ALICE, now=5)
    # once it clears
    assert rl.allowed(ALICE, now=11)


def test_hourly_cap_blocks_extra_replies():
    rl = RateLimiter(cooldown=0, hourly_cap=3)
    for i in range(3):
        assert rl.allowed(BOB, now=i)
        rl.record(BOB, now=i)
    # fourth within the hour is refused
    assert not rl.allowed(BOB, now=3)


def test_hourly_cap_prunes_old_hits():
    rl = RateLimiter(cooldown=0, hourly_cap=3)
    for i in range(3):
        rl.record(BOB, now=i)
    assert not rl.allowed(BOB, now=10)
    # an hour after the first hit it drops out and frees a slot
    assert rl.allowed(BOB, now=3600)


def test_users_are_independent():
    rl = RateLimiter(cooldown=10, hourly_cap=1)
    rl.record(ALICE, now=0)
    assert not rl.allowed(ALICE, now=1)
    # bob is untouched by alice's usage
    assert rl.allowed(BOB, now=1)
