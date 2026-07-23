"""Locate and invoke plan-cli.

plan-cli is the only writer of tasks.db. This module is the single place that
knows how to reach it, so the rest of the package never shells out ad hoc.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class PlanCliError(RuntimeError):
    """plan-cli could not be found, or exited non-zero."""


def resolve_plan_cli() -> list[str]:
    """Return the argv prefix that runs plan-cli.

    Resolution order (first hit wins):
      1. $PLAN_CLI_BIN            — explicit override (a `plan` binary or bin/plan.js)
      2. `plan` on PATH           — the normal host-terminal install
      3. $PLAN_CLI_HOME/bin/plan.js
      4. $WORKSPACE/github/plan-cli/bin/plan.js  — the conventional checkout

    A `.js` target is run through the current `node`; anything else is executed
    directly.
    """
    candidates: list[Path] = []

    explicit = os.environ.get("PLAN_CLI_BIN")
    if explicit:
        candidates.append(Path(explicit))

    on_path = shutil.which("plan")
    if on_path:
        candidates.append(Path(on_path))

    home = os.environ.get("PLAN_CLI_HOME")
    if home:
        candidates.append(Path(home) / "bin" / "plan.js")

    workspace = os.environ.get("WORKSPACE")
    if workspace:
        candidates.append(Path(workspace) / "github" / "plan-cli" / "bin" / "plan.js")

    for path in candidates:
        if path.is_file():
            if path.suffix == ".js":
                node = shutil.which("node")
                if not node:
                    raise PlanCliError(
                        f"Found plan-cli at {path} but no `node` on PATH to run it."
                    )
                log.info("DONE stage=resolve plan_cli=%s runner=node", path)
                return [node, str(path)]
            log.info("DONE stage=resolve plan_cli=%s runner=direct", path)
            return [str(path)]

    raise PlanCliError(
        "Could not find plan-cli. Tried: $PLAN_CLI_BIN, `plan` on PATH, "
        "$PLAN_CLI_HOME/bin/plan.js, $WORKSPACE/github/plan-cli/bin/plan.js. "
        "Set PLAN_CLI_BIN to the plan-cli entry point."
    )


def _run(args: list[str]) -> subprocess.CompletedProcess:
    argv = resolve_plan_cli() + args
    log.info("START stage=plan_cli args=%s", " ".join(args))
    proc = subprocess.run(argv, capture_output=True, text=True)
    if proc.returncode != 0:
        log.error(
            "FAIL stage=plan_cli args=%s code=%d stderr=%s",
            " ".join(args),
            proc.returncode,
            proc.stderr.strip()[:500],
        )
        raise PlanCliError(
            f"plan-cli exited {proc.returncode} for `{' '.join(args)}`:\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc


def read_backlog() -> dict:
    """Return the current backlog as {"active": task|None, "tasks": [task, ...]}."""
    proc = _run(["backlog", "--json"])
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        log.error("FAIL stage=parse_json reason=%s", err)
        raise PlanCliError(
            f"plan-cli `backlog --json` did not return JSON: {proc.stdout[:300]}"
        ) from err
    log.info(
        "DONE stage=read_backlog tasks=%d active=%s",
        len(payload.get("tasks", [])),
        bool(payload.get("active")),
    )
    return payload


def apply_backlog(markdown_path: Path) -> str:
    """Apply a rendered backlog file. Returns plan-cli's change summary."""
    proc = _run(["backlog", "--apply", str(markdown_path)])
    summary = proc.stdout.strip()
    log.info("DONE stage=apply_backlog file=%s", markdown_path)
    return summary


def planning_dir() -> Path:
    """Where plan-cli keeps backlog.md / tasks.db.

    Mirrors plan-cli's own resolution (PLANNING_DIR, else ~/planning), so the
    week doc lands next to the backlog on both host and container.
    """
    configured = os.environ.get("PLANNING_DIR")
    return Path(configured) if configured else Path.home() / "planning"
