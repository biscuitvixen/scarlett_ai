import asyncio

import pytest

from scarlett.db import Database
from scarlett.roles import (
    MAX_ENTRIES,
    Panel,
    PanelEntry,
    PanelMode,
    RoleRejection,
    check_assignable,
    decode_custom_id,
    encode_custom_id,
    final_roles,
    pack_rows,
    resolve_click,
)

# roles on the panel under test, plus one the member holds from elsewhere
FOX = 100
WOLF = 200
OTTER = 300
PANEL_ROLES = frozenset({FOX, WOLF, OTTER})
UNRELATED = 999


def panel(mode=PanelMode.MULTI, entries=()):
    return Panel(
        guild_id=1,
        name="pronouns",
        channel_id=2,
        mode=mode,
        title="Pick",
        entries=entries,
    )


def entries(*role_ids):
    return tuple(PanelEntry(i, r, f"role-{r}") for i, r in enumerate(role_ids))


@pytest.mark.parametrize(
    "mode, held, expect_add, expect_remove",
    [
        # not held: every mode grants it
        (PanelMode.MULTI, set(), {FOX}, set()),
        (PanelMode.SINGLE, set(), {FOX}, set()),
        (PanelMode.STICKY, set(), {FOX}, set()),
        # already held: multi and single give it back, sticky refuses
        (PanelMode.MULTI, {FOX}, set(), {FOX}),
        (PanelMode.SINGLE, {FOX}, set(), {FOX}),
        (PanelMode.STICKY, {FOX}, set(), set()),
    ],
)
def test_click_on_own_role(mode, held, expect_add, expect_remove):
    change = resolve_click(mode, FOX, held, PANEL_ROLES)
    assert change.add == expect_add, f"{mode} added the wrong roles"
    assert change.remove == expect_remove, f"{mode} removed the wrong roles"


def test_single_mode_strips_the_sibling():
    change = resolve_click(PanelMode.SINGLE, FOX, {WOLF}, PANEL_ROLES)
    assert change.add == {FOX}, "the clicked role should be granted"
    assert change.remove == {WOLF}, "the other panel role should be dropped"


def test_single_mode_strips_every_sibling_not_just_one():
    # a member can hold several panel roles if they were assigned by hand
    # before the panel existed
    change = resolve_click(PanelMode.SINGLE, FOX, {WOLF, OTTER}, PANEL_ROLES)
    assert change.add == {FOX}, "the clicked role should be granted"
    assert change.remove == {
        WOLF,
        OTTER,
    }, "every sibling should be dropped, not just the first"


@pytest.mark.parametrize("mode", list(PanelMode))
def test_roles_from_outside_the_panel_are_never_touched(mode):
    change = resolve_click(mode, FOX, {UNRELATED}, PANEL_ROLES)
    assert UNRELATED not in change.remove, f"{mode} touched an unrelated role"
    assert UNRELATED not in change.add, f"{mode} granted an unrelated role"


def test_single_mode_swap_is_expressed_as_one_final_set():
    # applied as a single write, so there is no moment holding both or neither
    change = resolve_click(PanelMode.SINGLE, FOX, {WOLF, UNRELATED}, PANEL_ROLES)
    assert final_roles({WOLF, UNRELATED}, change) == {
        FOX,
        UNRELATED,
    }, "the swap should land in one role set"


def test_no_change_reports_itself_as_unchanged():
    change = resolve_click(PanelMode.STICKY, FOX, {FOX}, PANEL_ROLES)
    assert not change.changed, "a no-op sticky click should report no change"


@pytest.mark.parametrize("mode", list(PanelMode))
def test_custom_id_round_trips(mode):
    raw = encode_custom_id(mode, FOX)
    assert decode_custom_id(raw) == (mode, FOX), f"{mode} did not round trip"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "rr",
        "rr:multi",
        "rr:multi:notanumber",
        "rr:nosuchmode:100",
        "other:multi:100",
        "rr:multi:100:extra",
    ],
)
def test_foreign_custom_ids_decode_to_none(raw):
    # a panel message can carry components this module did not put there
    assert decode_custom_id(raw) is None, f"{raw!r} should not have decoded"


OK = {
    "has_manage_roles": True,
    "bot_outranks": True,
    "is_default": False,
    "is_managed": False,
}


def test_an_ordinary_role_is_assignable():
    assert check_assignable(**OK) is None, "a plain role should be assignable"


@pytest.mark.parametrize(
    "override, expected",
    [
        ({"has_manage_roles": False}, RoleRejection.NO_MANAGE_ROLES),
        ({"bot_outranks": False}, RoleRejection.OUTRANKED),
        ({"is_default": True}, RoleRejection.IS_DEFAULT),
        ({"is_managed": True}, RoleRejection.IS_MANAGED),
    ],
)
def test_unassignable_roles_are_rejected(override, expected):
    assert check_assignable(**{**OK, **override}) is expected, (
        f"{override} should have been rejected as {expected}"
    )


def test_role_shape_is_rejected_before_bot_permissions():
    # @everyone is never assignable by anyone, so the reason given should be
    # about the role and not send someone off to fix a permission
    rejection = check_assignable(
        has_manage_roles=False,
        bot_outranks=False,
        is_default=True,
        is_managed=False,
    )
    assert rejection is RoleRejection.IS_DEFAULT, (
        "the role's own shape should be reported ahead of the bot's permissions"
    )


def test_rows_hold_five_buttons_each():
    rows = pack_rows(entries(*range(1, 13)))
    assert [len(r) for r in rows] == [5, 5, 2], "buttons packed into wrong rows"


def test_rows_follow_position_not_insertion_order():
    shuffled = (
        PanelEntry(2, OTTER, "c"),
        PanelEntry(0, FOX, "a"),
        PanelEntry(1, WOLF, "b"),
    )
    assert [e.role_id for e in pack_rows(shuffled)[0]] == [
        FOX,
        WOLF,
        OTTER,
    ], "rows should be ordered by position"


def test_a_panel_cannot_exceed_discords_button_ceiling():
    with pytest.raises(ValueError):
        pack_rows(entries(*range(1, MAX_ENTRIES + 2)))


def test_adding_a_role_twice_replaces_rather_than_duplicates():
    p = panel(entries=entries(FOX, WOLF))
    updated = p.with_entry(PanelEntry(0, FOX, "new label"))
    assert len(updated.entries) == 2, "re-adding a role should not duplicate it"
    labels = {e.role_id: e.label for e in updated.entries}
    assert labels[FOX] == "new label", "re-adding a role should update its label"


def test_positions_stay_dense_after_a_removal():
    p = panel(entries=entries(FOX, WOLF, OTTER))
    updated = p.without_role(WOLF)
    assert [e.position for e in updated.ordered()] == [
        0,
        1,
    ], "positions should renumber densely after a removal"


def test_reordering_moves_one_role_and_shuffles_the_rest():
    p = panel(entries=entries(FOX, WOLF, OTTER))
    updated = p.with_role_at(OTTER, 0)
    assert [e.role_id for e in updated.ordered()] == [
        OTTER,
        FOX,
        WOLF,
    ], "the moved role should land at the requested position"


def test_reordering_past_the_end_clamps():
    p = panel(entries=entries(FOX, WOLF, OTTER))
    updated = p.with_role_at(FOX, 99)
    assert [e.role_id for e in updated.ordered()] == [
        WOLF,
        OTTER,
        FOX,
    ], "an out of range position should clamp to the end"


# the store half. asyncio.run rather than pytest-asyncio, so the test suite
# keeps pytest as its only dev dependency


def run_store(tmp_path, body):
    async def main():
        db = await Database.open(str(tmp_path / "test.db"))
        try:
            return await body(db)
        finally:
            await db.close()

    return asyncio.run(main())


def test_a_saved_panel_comes_back_intact(tmp_path):
    saved = panel(
        mode=PanelMode.SINGLE,
        entries=(
            PanelEntry(0, FOX, "Fox", "🦊"),
            PanelEntry(1, WOLF, "Wolf", None),
        ),
    )

    async def body(db):
        await db.save_panel(saved)
        return await db.get_panel(saved.guild_id, saved.name)

    loaded = run_store(tmp_path, body)
    assert loaded == saved, "a round-tripped panel should be unchanged"


def test_saving_a_panel_replaces_its_entries_rather_than_appending(tmp_path):
    async def body(db):
        await db.save_panel(panel(entries=entries(FOX, WOLF, OTTER)))
        await db.save_panel(panel(entries=entries(FOX)))
        return await db.get_panel(1, "pronouns")

    loaded = run_store(tmp_path, body)
    assert [e.role_id for e in loaded.entries] == [FOX], (
        "re-saving should replace the entry set, not add to it"
    )


def test_deleting_a_panel_takes_its_entries_with_it(tmp_path):
    # the cascade only fires because open() turns foreign keys on, which
    # sqlite leaves off per connection by default
    async def body(db):
        await db.save_panel(panel(entries=entries(FOX, WOLF)))
        await db.delete_panel(1, "pronouns")
        async with db.conn.execute("SELECT COUNT(*) FROM role_panel_entries") as cur:
            return (await cur.fetchone())[0]

    assert run_store(tmp_path, body) == 0, (
        "deleting a panel should cascade to its entries"
    )


def test_a_panel_is_findable_by_its_message(tmp_path):
    async def body(db):
        await db.save_panel(panel(entries=entries(FOX)))
        await db.set_message_id(1, "pronouns", 555)
        found = await db.panel_for_message(555)
        await db.set_message_id(1, "pronouns", None)
        return found, await db.panel_for_message(555)

    found, orphaned = run_store(tmp_path, body)
    assert found is not None, "a posted panel should be findable by message id"
    assert found.name == "pronouns", "the wrong panel came back"
    assert orphaned is None, (
        "a panel whose message is gone should no longer be findable by it"
    )


def test_panels_are_findable_by_the_roles_on_them(tmp_path):
    async def body(db):
        await db.save_panel(panel(entries=entries(FOX, WOLF)))
        return (
            await db.panels_with_role(1, WOLF),
            await db.panels_with_role(1, UNRELATED),
        )

    hit, miss = run_store(tmp_path, body)
    assert [p.name for p in hit] == ["pronouns"], (
        "a panel carrying the role should be found"
    )
    assert miss == [], "a role on no panel should find nothing"


def test_panels_in_other_guilds_are_invisible(tmp_path):
    # the shared-backend case: one database, several servers
    async def body(db):
        await db.save_panel(panel(entries=entries(FOX)))
        return await db.list_panels(2), await db.get_panel(2, "pronouns")

    listed, fetched = run_store(tmp_path, body)
    assert listed == [], "another guild's panels should not be listed"
    assert fetched is None, "another guild's panel should not be fetchable"
