from scarlett.ratelimit import RateLimiter

ALICE = 1
BOB = 2

# a long recover so decay is out of the picture unless a test wants it
NO_DECAY = 1e9


def make(**kw):
    args = dict(
        base=2,
        burst=2,
        factor=2,
        max_cooldown=1000,
        recover=NO_DECAY,
        hourly_cap=1000,
    )
    args.update(kw)
    return RateLimiter(**args)


def test_burst_sits_at_base_then_escalates():
    rl = make()  # base 2, burst 2, factor 2
    # first reply is free, no prior timestamp
    assert rl.allowed(ALICE, 0)
    rl.record(ALICE, 0)
    # inside the base gap
    assert not rl.allowed(ALICE, 1)
    # the burst replies stay at the base gap of 2s
    assert rl.allowed(ALICE, 2)
    rl.record(ALICE, 2)
    assert rl.allowed(ALICE, 4)
    rl.record(ALICE, 4)
    # now past the burst, the gap has doubled to 4s
    assert not rl.allowed(ALICE, 6)
    assert rl.allowed(ALICE, 8)
    rl.record(ALICE, 8)
    # and doubled again to 8s
    assert not rl.allowed(ALICE, 12)
    assert rl.allowed(ALICE, 16)


def test_quiet_time_heals_the_cooldown():
    rl = make(burst=0, recover=10)  # escalates from the very first reply
    rl.record(ALICE, 0)
    # level 1 -> gap base*factor = 4s
    assert not rl.allowed(ALICE, 2)
    # after a long quiet the level decays back to zero and the gap is base
    assert rl.allowed(ALICE, 100)


def test_cooldown_is_capped():
    rl = make(base=10, burst=0, factor=10, max_cooldown=15)
    rl.record(ALICE, 0)
    # 10 * 10 would be 100s, but the cap holds it at 15s
    assert not rl.allowed(ALICE, 14)
    assert rl.allowed(ALICE, 15)


def test_hourly_cap_is_the_hard_ceiling():
    rl = make(base=0, hourly_cap=3)  # no cooldown, only the hourly cap bites
    for i in range(3):
        assert rl.allowed(BOB, i)
        rl.record(BOB, i)
    assert not rl.allowed(BOB, 3)
    # an hour after the first hit a slot frees up
    assert rl.allowed(BOB, 3600)


def test_users_are_independent():
    rl = make(burst=0, factor=100)
    rl.record(ALICE, 0)
    assert not rl.allowed(ALICE, 1)
    # bob's level and cooldown are untouched by alice
    assert rl.allowed(BOB, 1)
