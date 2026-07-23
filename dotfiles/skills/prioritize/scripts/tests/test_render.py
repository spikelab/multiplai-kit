"""Render tests.

These lock the contract with plan-cli's markdown parser. The invariants that
matter: every task is emitted every time (rank is file order), importance is
carried by the section heading, and exactly one line gets `[now]`.
"""

import re

import pytest

from prioritize_session import render
from prioritize_session.render import ChangesetError


def task(**overrides):
    base = {
        "id": 1,
        "title": "Something",
        "type": "sales",
        "importance": "medium",
        "due": None,
        "duration": None,
        "rank": 1,
        "status": "backlog",
    }
    base.update(overrides)
    return base


def backlog(active=None, tasks=()):
    return {"active": active, "tasks": list(tasks)}


def task_lines(markdown: str) -> list[str]:
    return [ln for ln in markdown.splitlines() if ln.startswith("- [")]


def task_ids(markdown: str) -> list[int]:
    """Ids in file order — which is exactly what plan-cli turns into rank."""
    matches = [re.match(r"- \[[ x]\] \[(\d+)\]", ln) for ln in task_lines(markdown)]
    assert all(matches), "every task line must match plan-cli's parser"
    return [int(m.group(1)) for m in matches if m]


class TestRenderTaskLine:
    def test_matches_plan_cli_format(self):
        line = render.render_task_line(
            task(id=7, title="Write the deck", type="client-work", due="2026-07-25", duration=90)
        )
        assert line == "- [ ] [7] Write the deck `client-work` — due 2026-07-25 ~90min"

    def test_no_extras_segment_when_there_is_nothing_to_say(self):
        assert render.render_task_line(task(id=7, title="Ping Bob", type=None)) == "- [ ] [7] Ping Bob"

    def test_now_and_importance_tokens(self):
        line = render.render_task_line(
            task(id=7, title="Ping Bob", type=None), now=True, importance_token="high"
        )
        assert line == "- [ ] [7] [high] [now] Ping Bob"

    def test_done_renders_a_checked_box(self):
        assert render.render_task_line(task(id=7, title="X", type=None, done=True)).startswith("- [x] [7]")

    def test_absent_due_does_not_emit_a_clear_token(self):
        assert "due none" not in render.render_task_line(task(due=None))

    def test_explicitly_cleared_due_emits_the_clear_token(self):
        assert "due none" in render.render_task_line(task(due=None, _clear_due=True))


class TestApplyUpdates:
    def test_updates_are_folded_in(self):
        tasks, _ = render.apply_updates(
            backlog(tasks=[task(id=3, importance="low")]),
            {"updates": {"3": {"importance": "high", "due": "2026-08-01"}}},
        )
        assert tasks[0]["importance"] == "high"
        assert tasks[0]["due"] == "2026-08-01"

    def test_active_task_is_included(self):
        tasks, now_id = render.apply_updates(
            backlog(active=task(id=9, status="active"), tasks=[task(id=3)]), {}
        )
        assert [t["id"] for t in tasks] == [9, 3]
        assert now_id == 9

    def test_omitting_now_keeps_the_current_focus(self):
        _, now_id = render.apply_updates(backlog(active=task(id=9), tasks=[task(id=3)]), {})
        assert now_id == 9

    def test_now_null_clears_the_focus(self):
        _, now_id = render.apply_updates(
            backlog(active=task(id=9), tasks=[task(id=3)]), {"now": None}
        )
        assert now_id is None

    def test_now_can_move_to_another_task(self):
        _, now_id = render.apply_updates(
            backlog(active=task(id=9), tasks=[task(id=3)]), {"now": 3}
        )
        assert now_id == 3

    @pytest.mark.parametrize(
        "changeset,message",
        [
            ({"updates": {"99": {"importance": "high"}}}, "not in the current backlog"),
            ({"updates": {"3": {"urgency": "high"}}}, "unknown update field"),
            ({"updates": {"3": {"importance": "critical"}}}, "importance must be one of"),
            ({"updates": {"3": {"type": "nonsense"}}}, "type must be one of"),
            ({"updates": {"3": {"due": "next friday"}}}, "due must be YYYY-MM-DD"),
            ({"updates": {"3": {"duration": None}}}, "cannot be cleared"),
            ({"updates": {"3": {"duration": 0}}}, "positive integer"),
            ({"updates": {"3": {"title": ""}}}, "cannot be empty"),
            ({"now": 99}, "not in the current backlog"),
        ],
    )
    def test_bad_changesets_are_rejected(self, changeset, message):
        with pytest.raises(ChangesetError, match=message):
            render.apply_updates(backlog(tasks=[task(id=3)]), changeset)

    def test_now_on_a_task_being_completed_is_rejected(self):
        with pytest.raises(ChangesetError, match="also marked done"):
            render.apply_updates(
                backlog(tasks=[task(id=3)]), {"now": 3, "updates": {"3": {"done": True}}}
            )

    def test_title_with_the_extras_separator_is_rejected(self):
        # plan-cli would truncate the title at " — " and read the rest as extras.
        with pytest.raises(ChangesetError, match="truncated"):
            render.apply_updates(
                backlog(tasks=[task(id=3)]),
                {"updates": {"3": {"title": "Call Bob — then email"}}},
            )

    def test_existing_bad_title_is_caught_even_without_an_update(self):
        with pytest.raises(ChangesetError, match="truncated"):
            render.apply_updates(backlog(tasks=[task(id=3, title="A — B")]), {})

    def test_title_ending_in_a_backtick_word_is_rejected(self):
        with pytest.raises(ChangesetError, match="task type"):
            render.apply_updates(
                backlog(tasks=[task(id=3)]), {"updates": {"3": {"title": "Fix the `db`"}}}
            )


class TestOrdering:
    def test_listed_ids_float_to_the_top_in_the_given_order(self):
        tasks = [task(id=1, rank=1), task(id=2, rank=2), task(id=3, rank=3)]
        assert [t["id"] for t in render.order_tasks(tasks, [3, 1])] == [3, 1, 2]

    def test_unlisted_tasks_keep_their_relative_rank_order(self):
        tasks = [task(id=1, rank=5), task(id=2, rank=2), task(id=3, rank=9)]
        assert [t["id"] for t in render.order_tasks(tasks, [])] == [2, 1, 3]

    def test_unranked_tasks_sink_to_the_bottom(self):
        tasks = [task(id=1, rank=None), task(id=2, rank=4)]
        assert [t["id"] for t in render.order_tasks(tasks, None)] == [2, 1]

    def test_unknown_id_in_order_is_rejected(self):
        with pytest.raises(ChangesetError, match="not in the backlog"):
            render.order_tasks([task(id=1)], [1, 42])


class TestRenderBacklog:
    def test_every_task_is_emitted_even_when_untouched(self):
        # Rank is file order in plan-cli's parser — a partial file renumbers
        # silently, so this is the invariant that protects the backlog.
        bl = backlog(tasks=[task(id=i, rank=i) for i in (1, 2, 3, 4, 5)])
        markdown = render.render_backlog(bl, {"updates": {"3": {"importance": "high"}}})
        assert len(task_lines(markdown)) == 5

    def test_sections_are_ordered_high_medium_low(self):
        bl = backlog(
            tasks=[
                task(id=1, importance="low"),
                task(id=2, importance="high"),
                task(id=3, importance="medium"),
            ]
        )
        markdown = render.render_backlog(bl, {})
        headings = [ln for ln in markdown.splitlines() if ln.startswith("## ")]
        assert headings == ["## High", "## Medium", "## Low"]

    def test_a_task_lands_under_its_updated_importance(self):
        bl = backlog(tasks=[task(id=1, importance="low", title="Promote me", type=None)])
        markdown = render.render_backlog(bl, {"updates": {"1": {"importance": "high"}}})
        assert "## High\n- [ ] [1] Promote me" in markdown
        assert "## Low" not in markdown

    def test_focus_line_carries_an_explicit_importance_token(self):
        # The `## Now` heading isn't a section marker for plan-cli, so without
        # an inline token the focus task's importance would be left unset.
        bl = backlog(active=task(id=9, importance="high", title="Focus", type=None))
        markdown = render.render_backlog(bl, {})
        assert "- [ ] [9] [high] [now] Focus" in markdown

    def test_exactly_one_now_marker(self):
        bl = backlog(active=task(id=9), tasks=[task(id=1), task(id=2)])
        markdown = render.render_backlog(bl, {"now": 2})
        assert sum("[now]" in ln for ln in task_lines(markdown)) == 1

    def test_clearing_focus_puts_the_task_back_in_its_section(self):
        bl = backlog(active=task(id=9, importance="high", title="Was focus", type=None))
        markdown = render.render_backlog(bl, {"now": None})
        assert "[now]" not in markdown
        assert "## High\n- [ ] [9] Was focus" in markdown

    def test_done_tasks_render_checked_outside_the_importance_sections(self):
        bl = backlog(tasks=[task(id=1, importance="high", title="Live", type=None),
                            task(id=2, importance="high", title="Finished", type=None)])
        markdown = render.render_backlog(bl, {"updates": {"2": {"done": True}}})
        assert "- [x] [2] Finished" in markdown
        assert "## Completed this session" in markdown
        # Done lines must not sit under an importance heading — plan-cli takes
        # the done branch before ranking, but a stray heading would still be a
        # trap for the next reader.
        body, _, completed = markdown.partition("## Completed this session")
        assert "- [x]" not in body
        assert "## High" not in completed

    def test_order_only_applies_within_a_section(self):
        bl = backlog(
            tasks=[
                task(id=1, importance="high", rank=1),
                task(id=2, importance="low", rank=2),
                task(id=3, importance="high", rank=3),
            ]
        )
        markdown = render.render_backlog(bl, {"order": [2, 3]})
        # 2 is low, so it can't outrank the high items no matter what order says.
        assert task_ids(markdown) == [3, 1, 2]

    def test_empty_backlog_renders_without_crashing(self):
        markdown = render.render_backlog(backlog(), {})
        assert task_lines(markdown) == []
