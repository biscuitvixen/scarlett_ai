from scarlett.health import MAX_STALENESS, check, write_heartbeat


def test_fresh_heartbeat_passes(tmp_path):
    path = tmp_path / "heartbeat"
    write_heartbeat(path)
    assert check(path) is None


def test_missing_file_fails(tmp_path):
    assert check(tmp_path / "nope") == "no heartbeat yet"


def test_garbage_file_fails(tmp_path):
    path = tmp_path / "heartbeat"
    path.write_text("not a number")
    assert check(path) == "no heartbeat yet"


def test_stale_heartbeat_fails(tmp_path):
    path = tmp_path / "heartbeat"
    path.write_text("1000.0")
    # a beat MAX_STALENESS + 10s in the past has gone stale
    assert check(path, now=1000.0 + MAX_STALENESS + 10) is not None


def test_heartbeat_just_within_window_passes(tmp_path):
    path = tmp_path / "heartbeat"
    path.write_text("1000.0")
    assert check(path, now=1000.0 + MAX_STALENESS - 1) is None
