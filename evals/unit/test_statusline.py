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

import pytest

from _kitpaths import KIT_ROOT

SCRIPT = KIT_ROOT / "dotfiles" / "scripts" / "statusline.sh"

ANSI = re.compile(r"\033\[[0-9;]*m")


def payload(**overrides):
    """A realistic statusline payload; keys set to None are removed."""
    now = int(time.time())
    # The five-hour reset is deliberately **off** the minute boundary. The
    # statusline floors the countdown against its own `date +%s`, so a payload
    # built at exactly `now + 5400` renders `1h30m` only while the two clocks
    # agree to the second — one tick of drift between building this dict and
    # the script reading the time floors it to `1h29m`. That is a test racing
    # a wall clock, not a bug in the countdown, and it failed CI on 2026-08-08.
    # The extra 30s buys half a minute of slack in both directions.
    base = {
        "model": {"id": "claude-opus-5[1m]", "display_name": "Opus 5 (1M context)"},
        "workspace": {"current_dir": "/host/home/someone/workspace"},
        "cwd": "/host/home/someone/workspace",
        "context_window": {"used_percentage": 8},
        "effort": {"level": "medium"},
        "rate_limits": {
            "five_hour": {"used_percentage": 72, "resets_at": now + 5400 + 30},
            "seven_day": {"used_percentage": 52, "resets_at": now + 180000},
        },
        "prompt_cache": {
            "warm": True,
            "caching_observed": True,
            "ttl": "1h",
            "expires_at": now + 2520 + 30,
            "requests": 14,
            "misses": 0,
            "hit_ratio": 0.914,
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


@pytest.mark.parametrize(
    "path,shown",
    [
        ("/host/home/someone/workspace/.worktrees/statusline-cache", "wt:statusline-cache"),
        ("/host/home/someone/workspace/.worktrees/statusline-cache/evals", "wt:statusline-cache/evals"),
        ("/repo/.claude/worktrees/fix-worktree-bug", "wt:fix-worktree-bug"),
        (
            "/host/home/someone/workspace/.worktrees/statusline-cache/dotfiles/scripts/lib",
            "wt:statusline-cache/.../lib",
        ),
    ],
)
def test_worktree_path_collapses_to_its_name(path, shown):
    out = run(payload(workspace={"current_dir": path}, cwd=path))
    assert f"| {shown} |" in out


def test_the_worktrees_directory_itself_is_not_a_worktree():
    path = "/host/home/someone/workspace/.worktrees"
    out = run(payload(workspace={"current_dir": path}, cwd=path))
    assert "wt:" not in out
    assert "| ~/.worktrees |" in out


def test_missing_rate_limits_drops_the_segments_cleanly():
    out = run(payload(rate_limits=None))
    assert "5h" not in out
    assert "7d" not in out


def test_a_wrongly_typed_subtree_only_costs_its_own_fields():
    """One jq pass extracts every field, so an error anywhere in the
    program aborts all of them. `//` covers null but not a type error: with
    `rate_limits` a string rather than an object, `.rate_limits.five_hour`
    raises, jq exits non-zero and prints nothing, and the statusline loses
    model, directory and context% along with the usage segments — an empty
    directory then breaks the `git -C` probe too. Each field is wrapped `(...)?`
    so a bad subtree costs only itself."""
    out = run(payload(rate_limits="unavailable"))
    assert "Opus 5 1M" in out
    assert "8%" in out
    assert "5h" not in out
    assert "7d" not in out


def test_a_newline_inside_a_value_does_not_truncate_the_record():
    """The fields arrive as one delimited record. A plain `read` stops at
    the first newline, so a newline in any value would silently empty every
    field after it — here, everything downstream of the model name. The
    record is NUL-terminated and read with `-d ''` instead."""
    out = run(payload(model={"display_name": "Opus\n5"}))
    assert "5h 72%" in out
    assert "7d 52%" in out
    assert not out.rstrip().endswith("|")


def test_missing_effort_drops_the_segment():
    assert "med" not in run(payload(effort=None))


@pytest.mark.parametrize(
    "level,shown", [("low", "lo"), ("medium", "med"), ("high", "hi"), ("xhigh", "xhi"), ("max", "max")]
)
def test_effort_is_abbreviated(level, shown):
    out = run(payload(effort={"level": level}))
    assert out.startswith(f"Opus 5 1M {shown} | ")


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


def test_output_style_is_not_shown():
    out = run(payload(output_style={"name": "Clear Writing"}))
    assert "Clear Writing" not in out


def test_warm_cache_shows_hit_ratio_and_time_until_cold():
    out = run(payload())
    assert out.endswith("cache 91% ⟳42m")


def test_cold_cache_says_cold_instead_of_a_countdown():
    data = payload()
    data["prompt_cache"].update(warm=False, expires_at=None)
    out = run(data)
    assert "cache 91% cold" in out
    assert "⟳42m" not in out


def test_cache_misses_show_only_when_there_are_some():
    assert "✗" not in run(payload())
    data = payload()
    data["prompt_cache"]["misses"] = 2
    assert run(data).endswith("⟳42m ✗2")


def test_null_hit_ratio_drops_only_the_percentage():
    data = payload()
    data["prompt_cache"]["hit_ratio"] = None
    assert run(data).endswith("cache ⟳42m")


def test_caching_not_observed_says_off():
    data = payload()
    data["prompt_cache"].update(
        caching_observed=False, warm=False, expires_at=None, hit_ratio=None
    )
    assert run(data).endswith("cache off")


def test_missing_prompt_cache_drops_the_segment_cleanly():
    out = run(payload(prompt_cache=None))
    assert "cache" not in out
    assert not out.rstrip().endswith("|")


def test_cache_hit_ratio_is_color_coded_with_high_as_good():
    def color_of(ratio):
        data = payload()
        data["prompt_cache"]["hit_ratio"] = ratio
        raw = subprocess.run(
            ["bash", str(SCRIPT)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": "/home/agent", "STATUSLINE_TZ": "UTC"},
            check=True,
        ).stdout
        match = re.search(r"cache (\033\[\d+m)", raw)
        assert match, f"no color code before the cache percentage in {raw!r}"
        return match.group(1)

    green, yellow, red = "\033[32m", "\033[33m", "\033[31m"
    assert color_of(0.95) == green
    assert color_of(0.6) == yellow
    assert color_of(0.1) == red
