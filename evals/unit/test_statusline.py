"""Tests for dotfiles/scripts/statusline.sh.

Two failure modes motivated these, and both are silent — the statusline has no
error channel, so a broken segment just looks like a segment nobody added.

1. **Width.** Everything past the terminal's last column is truncated, and the
   usage segments sit at the far right. The model name and an absolute host path
   were together worth ~45 columns.
2. **Absent fields.** `rate_limits` only exists for Claude.ai subscribers and
   only after the session's first API response; `effort` is absent on models
   without the parameter. Both must degrade to "segment missing", not to a
   crash or a stray separator.
"""

import json
import re
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "dotfiles" / "scripts" / "statusline.sh"

ANSI = re.compile(r"\033\[[0-9;]*m")


def payload(**overrides):
    """A realistic statusline payload; keys set to None are removed."""
    now = int(time.time())
    base = {
        "model": {"id": "claude-opus-5[1m]", "display_name": "Opus 5 (1M context)"},
        "workspace": {"current_dir": "/host/home/someone/workspace"},
        "cwd": "/host/home/someone/workspace",
        "context_window": {"used_percentage": 8},
        "effort": {"level": "medium"},
        "rate_limits": {
            "five_hour": {"used_percentage": 72, "resets_at": now + 5400},
            "seven_day": {"used_percentage": 52, "resets_at": now + 180000},
        },
    }
    for key, value in overrides.items():
        if value is None:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def run(data, env=None):
    """Run the statusline and return its output with ANSI codes stripped."""
    full_env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": "/home/agent",
        "WORKSPACE": "/host/home/someone/workspace",
        "STATUSLINE_TZ": "UTC",
    }
    full_env.update(env or {})
    proc = subprocess.run(
        ["bash", str(SCRIPT)],
        input=json.dumps(data),
        capture_output=True,
        text=True,
        env=full_env,
        check=True,
    )
    return ANSI.sub("", proc.stdout)


def test_shows_both_usage_windows():
    out = run(payload())
    assert "5h 72%" in out
    assert "7d 52%" in out


def test_five_hour_reset_is_relative_and_seven_day_is_a_weekday():
    out = run(payload())
    assert "⟳1h30m" in out
    assert re.search(r"⟳(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d\d:\d\d", out)


def test_expired_reset_does_not_render_a_negative_countdown():
    data = payload()
    data["rate_limits"]["five_hour"]["resets_at"] = int(time.time()) - 60
    assert "⟳0m" in run(data)


def test_fits_in_eighty_columns():
    # The whole point of the model/path shortening. 80 is the narrowest common
    # terminal; past it the usage segments are the first thing to disappear.
    assert len(run(payload())) <= 80


def test_workspace_root_collapses_to_tilde():
    out = run(payload())
    assert "~" in out
    # Bash tilde-expands a bare `~` in a ${var/#pat/~} replacement, which used to
    # turn the collapsed path straight back into $HOME.
    assert "/home/agent" not in out
    assert "/host/home/someone" not in out


def test_deep_path_keeps_the_last_two_components():
    deep = "/host/home/someone/workspace/PROJECTS/multiplai-kit/scripts"
    out = run(payload(workspace={"current_dir": deep}, cwd=deep))
    assert ".../multiplai-kit/scripts" in out


def test_missing_rate_limits_drops_the_segments_cleanly():
    out = run(payload(rate_limits=None))
    assert "5h" not in out
    assert "7d" not in out
    assert not out.rstrip().endswith("|")


def test_missing_effort_drops_the_segment():
    assert "med" not in run(payload(effort=None))


@pytest.mark.parametrize(
    "level,shown", [("low", "lo"), ("medium", "med"), ("high", "hi"), ("xhigh", "xhi"), ("max", "max")]
)
def test_effort_is_abbreviated(level, shown):
    out = run(payload(effort={"level": level}))
    assert f"| {shown} |" in out


def test_workspace_falls_back_to_the_dotfile(tmp_path):
    # Bare/host sessions have no $WORKSPACE; setup.sh always writes .workspace.
    (tmp_path / ".workspace").write_text("/host/home/someone/workspace\n")
    out = run(payload(), env={"WORKSPACE": "", "CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert "/host/home/someone" not in out


def test_timezone_falls_back_to_the_dotfile(tmp_path):
    (tmp_path / ".timezone").write_text("Pacific/Kiritimati\n")
    data = payload()
    # Fixed instant so the two zones land on different clock readings.
    data["rate_limits"]["seven_day"]["resets_at"] = 1786334400
    utc = run(data)
    other = run(data, env={"STATUSLINE_TZ": "", "CLAUDE_CONFIG_DIR": str(tmp_path)})
    assert utc != other


def test_percentages_are_color_coded_by_severity():
    def color_of(pct):
        data = payload()
        data["rate_limits"]["five_hour"]["used_percentage"] = pct
        raw = subprocess.run(
            ["bash", str(SCRIPT)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/home/agent", "STATUSLINE_TZ": "UTC"},
            check=True,
        ).stdout
        match = re.search(r"5h (\033\[\d+m)", raw)
        assert match, f"no color code before the 5h percentage in {raw!r}"
        return match.group(1)

    green, yellow, red = "\033[32m", "\033[33m", "\033[31m"
    assert color_of(10) == green
    assert color_of(50) == yellow
    assert color_of(80) == red
