from datetime import date
from pathlib import Path

import pytest

from prioritize_session import enrich

TODAY = date(2026, 7, 23)  # a Thursday


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
        "done_when": None,
        "captured": "2026-07-20",
        "notes": None,
        "start": None,
    }
    base.update(overrides)
    return base


class TestUrgency:
    @pytest.mark.parametrize(
        "due,expected_bucket,expected_days",
        [
            (None, "unscheduled", None),
            ("2026-07-20", "overdue", -3),
            ("2026-07-23", "urgent", 0),
            ("2026-07-25", "urgent", 2),
            ("2026-07-26", "soon", 3),
            ("2026-07-30", "soon", 7),
            ("2026-07-31", "later", 8),
        ],
    )
    def test_buckets(self, due, expected_bucket, expected_days):
        assert enrich.urgency_of(due, TODAY) == (expected_bucket, expected_days)

    def test_unparseable_due_is_unscheduled_not_a_crash(self):
        assert enrich.urgency_of("next friday", TODAY) == ("unscheduled", None)


class TestQuadrant:
    def test_high_and_due_soon_is_q1(self):
        assert enrich.quadrant_of("high", "urgent") == "Q1"

    def test_high_and_unscheduled_is_q2(self):
        assert enrich.quadrant_of("high", "unscheduled") == "Q2"

    def test_medium_counts_as_not_important(self):
        # The 3-into-2 collapse is deliberate; lock it so it can't drift silently.
        assert enrich.quadrant_of("medium", "urgent") == "Q3"
        assert enrich.quadrant_of("medium", "later") == "Q4"

    def test_missing_importance_defaults_to_medium(self):
        assert enrich.quadrant_of(None, "later") == "Q4"


class TestEnrichTask:
    def test_starved_flags_an_old_q2_item(self):
        out = enrich.enrich_task(
            task(importance="high", due=None, captured="2026-06-01"), TODAY
        )
        assert out["quadrant"] == "Q2"
        assert out["age_days"] == 52
        assert out["starved"] is True

    def test_fresh_q2_item_is_not_starved(self):
        out = enrich.enrich_task(
            task(importance="high", captured="2026-07-22"), TODAY
        )
        assert out["quadrant"] == "Q2"
        assert out["starved"] is False

    def test_urgent_item_is_never_starved(self):
        out = enrich.enrich_task(
            task(importance="high", due="2026-07-24", captured="2026-01-01"), TODAY
        )
        assert out["quadrant"] == "Q1"
        assert out["starved"] is False

    def test_sand_is_short_work(self):
        assert enrich.enrich_task(task(duration=10), TODAY)["sand"] is True
        assert enrich.enrich_task(task(duration=15), TODAY)["sand"] is True
        assert enrich.enrich_task(task(duration=20), TODAY)["sand"] is False
        assert enrich.enrich_task(task(duration=None), TODAY)["sand"] is False

    def test_rock_candidate_needs_high_importance_and_a_real_block(self):
        assert enrich.enrich_task(task(importance="high", duration=90), TODAY)["rock_candidate"]
        # Unestimated high-importance work counts — that's usually the big kind.
        assert enrich.enrich_task(task(importance="high", duration=None), TODAY)["rock_candidate"]
        assert not enrich.enrich_task(task(importance="high", duration=10), TODAY)["rock_candidate"]
        assert not enrich.enrich_task(task(importance="medium", duration=90), TODAY)["rock_candidate"]

    def test_brief_drops_the_bulky_fields(self):
        out = enrich.enrich_task(
            task(notes="a very long note", start=["step one", "step two"]), TODAY
        )
        assert "notes" not in out
        assert "start" not in out
        assert out["has_detail"] is True

    def test_has_detail_false_when_there_is_nothing_to_fetch(self):
        assert enrich.enrich_task(task(), TODAY)["has_detail"] is False


class TestBuildBrief:
    def test_counts_and_week_doc_path(self, tmp_path: Path):
        backlog = {
            "active": task(id=1, importance="high", due="2026-07-24"),
            "tasks": [
                task(id=2, importance="high", due=None, captured="2026-01-01"),
                task(id=3, importance="low", due="2026-12-01"),
                task(id=4, importance="medium", duration=10),
            ],
        }
        brief = enrich.build_brief(backlog, TODAY, tmp_path)

        assert brief["today"] == "2026-07-23"
        assert brief["week_of"] == "2026-07-20"  # the Monday
        assert brief["week_doc_path"] == str(tmp_path / "week-2026-07-20.md")
        assert brief["counts"]["total"] == 4
        assert brief["counts"]["Q1"] == 1
        assert brief["counts"]["Q2"] == 1
        assert brief["counts"]["Q4"] == 2
        assert brief["counts"]["starved"] == 1
        assert brief["counts"]["sand"] == 1
        assert brief["active"]["id"] == 1
        assert [t["id"] for t in brief["tasks"]] == [2, 3, 4]

    def test_empty_backlog(self, tmp_path: Path):
        brief = enrich.build_brief({"active": None, "tasks": []}, TODAY, tmp_path)
        assert brief["counts"]["total"] == 0
        assert brief["active"] is None
