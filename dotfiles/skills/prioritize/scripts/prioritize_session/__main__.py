"""CLI for the `prioritize` skill.

    python -m prioritize_session brief   --session-id ID [--snapshot]
    python -m prioritize_session detail  --session-id ID --ids 12,45
    python -m prioritize_session apply   --session-id ID --changes FILE [--dry-run]
    python -m prioritize_session revert  --session-id ID [--snapshot FILE]

Every subcommand prints JSON on stdout so the skill can read it directly;
errors go to stderr with a non-zero exit.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

from log_utils import setup_logging

from . import enrich, plan_cli, render, session

DETAIL_FIELDS = ("id", "title", "type", "importance", "due", "duration", "status",
                 "done_when", "notes", "start", "captured", "rank")


def _emit(payload: dict) -> None:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def cmd_brief(args, logger) -> int:
    backlog = plan_cli.read_backlog()
    brief = enrich.build_brief(backlog, date.today(), plan_cli.planning_dir())
    if args.snapshot:
        brief["snapshot_path"] = str(session.save_snapshot(backlog, args.session_id))
    _emit(brief)
    return 0


def cmd_detail(args, logger) -> int:
    wanted = {int(i) for i in args.ids.split(",") if i.strip()}
    backlog = plan_cli.read_backlog()
    everything = ([backlog["active"]] if backlog.get("active") else []) + backlog.get("tasks", [])
    found = [
        {k: t.get(k) for k in DETAIL_FIELDS} for t in everything if t["id"] in wanted
    ]
    missing = sorted(wanted - {t["id"] for t in found})
    if missing:
        logger.warning("SKIP stage=detail reason=not_in_backlog ids=%s", missing)
    _emit({"tasks": found, "missing": missing})
    return 0


def _apply_changeset(
    changeset: dict, session_id: str, dry_run: bool, logger, backlog: dict | None = None
) -> dict:
    if backlog is None:
        backlog = plan_cli.read_backlog()
    markdown = render.render_backlog(backlog, changeset)

    if dry_run:
        logger.info("SKIP stage=apply reason=dry_run")
        return {"dry_run": True, "markdown": markdown}

    snapshot_path = session.save_snapshot(backlog, session_id)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".md", prefix="prioritize-", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(markdown)
        temp_path = Path(handle.name)

    try:
        summary = plan_cli.apply_backlog(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)

    return {"applied": True, "snapshot_path": str(snapshot_path), "summary": summary}


def cmd_apply(args, logger) -> int:
    changeset = json.loads(Path(args.changes).read_text(encoding="utf-8"))
    _emit(_apply_changeset(changeset, args.session_id, args.dry_run, logger))
    return 0


def cmd_revert(args, logger) -> int:
    path = Path(args.snapshot) if args.snapshot else session.latest_snapshot()
    if path is None or not path.is_file():
        print(
            f"No snapshot to revert to (looked in {session.snapshot_dir()}).",
            file=sys.stderr,
        )
        return 1
    snapshot = session.load_snapshot(path)

    # Anything completed since the snapshot has left the backlog. Restore what's
    # still there and name what couldn't be — a partial revert of the ranking is
    # far more useful than refusing because one task got finished.
    backlog = plan_cli.read_backlog()
    present = {t["id"] for t in backlog.get("tasks", [])}
    if backlog.get("active"):
        present.add(backlog["active"]["id"])

    changeset, unrestorable = session.revert_changeset(snapshot, present)
    if unrestorable:
        logger.warning("SKIP stage=revert reason=left_backlog ids=%s", unrestorable)

    result = _apply_changeset(changeset, args.session_id, args.dry_run, logger, backlog)
    result["reverted_from"] = str(path)
    result["unrestorable"] = unrestorable
    _emit(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prioritize_session", description=__doc__)
    parser.add_argument("--session-id", default="", help="Claude Code session id, for log correlation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    brief = subparsers.add_parser("brief", help="Enriched backlog for the deliberation")
    brief.add_argument("--snapshot", action="store_true", help="Also save a pre-session snapshot")
    brief.set_defaults(func=cmd_brief)

    detail = subparsers.add_parser("detail", help="Full fields (notes, first steps) for specific tasks")
    detail.add_argument("--ids", required=True, help="Comma-separated task ids")
    detail.set_defaults(func=cmd_detail)

    apply_cmd = subparsers.add_parser("apply", help="Apply a decision changeset via plan-cli")
    apply_cmd.add_argument("--changes", required=True, help="Path to the changeset JSON")
    apply_cmd.add_argument("--dry-run", action="store_true", help="Render the markdown, write nothing")
    apply_cmd.set_defaults(func=cmd_apply)

    revert = subparsers.add_parser("revert", help="Restore a pre-session snapshot")
    revert.add_argument("--snapshot", help="Snapshot file (defaults to the most recent)")
    revert.add_argument("--dry-run", action="store_true", help="Render the markdown, write nothing")
    revert.set_defaults(func=cmd_revert)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = setup_logging("prioritize", session_id=args.session_id, package="prioritize_session")
    logger.info("START stage=%s", args.command)
    try:
        code = args.func(args, logger)
    except (plan_cli.PlanCliError, render.ChangesetError) as err:
        logger.error("FAIL stage=%s reason=%s", args.command, err)
        print(f"{err}", file=sys.stderr)
        return 1
    logger.info("DONE stage=%s code=%d", args.command, code)
    return code


if __name__ == "__main__":
    sys.exit(main())
