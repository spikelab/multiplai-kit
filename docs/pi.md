# Running pi in the multiplai container

`./pi.sh` launches the [pi coding agent](https://pi.dev) inside the same
container `./claude.sh` uses, with the same workspace mounts, git identity, GH
token, env forwarding and SSH host bridge. It is a wrapper around
`claude.sh --pi`, not a second launcher.

```bash
./pi.sh                          # pi on the deepseek profile
./pi.sh --pi-profile kimi        # a different model profile
./pi.sh --profile work           # work git identity, deepseek profile
./pi.sh -p "summarise this repo" # pi's own flags pass straight through
```

## Two things are called "profile"

They are different axes and they compose.

| Flag | Selects | Lives in |
|---|---|---|
| `--profile <name>` | git identity + GH token | `env.<name>` |
| `--pi-profile <name>` | pi model configuration | `dotfiles/pi-profiles/<name>/` (template), `~/.claude-container/pi/<name>/` (live) |

## What a pi profile is

The whole `~/.pi` directory: `models.json`, credentials, installed packages,
and session history. pi resolves its config from `homedir()/.pi/agent` with no
environment-variable override (checked in 0.84.2), so a profile is implemented
by mounting a *different host directory* at that one container path.

The consequence is worth stating plainly: **profiles are fully isolated.**
Different models, different API keys, different extensions, different session
history. Nothing leaks between them, and you cannot half-switch.

The template under `dotfiles/pi-profiles/<name>/` is in git and is only ever
copied into the live directory when a file is *absent*. Anything you or pi
subsequently write — `/settings`, `pi install`, `pi auth` — wins over the
template and survives the next launch.

## How pi gets into the container

It is not in the image. The image already ships Node 22 and npm, which is all
pi needs, so `scripts/pi-bootstrap.sh` installs it into a user-owned npm prefix
at `~/.pi-cli` on first launch and caches it there across containers. That
keeps pi upgradable without cutting a container release.

The version is pinned in the bootstrap (`MULTIPLAI_PI_VERSION`, currently
0.84.2) and compared on every launch, so a bump reinstalls and a match costs
nothing. Two containers starting at once contend on a lock rather than running
npm over each other.

## The deepseek profile

Two things make pi effective with DeepSeek, and they are independent.

### 1. The compat block, or thinking-mode tool calls fail

DeepSeek's API is OpenAI-compatible but not OpenAI-identical. `models.json`
sets, at provider level:

| Field | Value | Why |
|---|---|---|
| `thinkingFormat` | `"deepseek"` | DeepSeek takes `thinking: {type: enabled}`, not OpenAI's reasoning param |
| `requiresReasoningContentOnAssistantMessages` | `true` | `reasoning_content` must survive replay across tool-call turns |
| `supportsReasoningEffort` | `true` | enables the Shift+Tab thinking selector |
| `supportsDeveloperRole` | `false` | DeepSeek rejects the `developer` role; send `system` |
| `maxTokensField` | `"max_tokens"` | DeepSeek's naming, not `max_completion_tokens` |

Per model, `thinkingLevelMap` marks `minimal`/`low`/`medium`/`xhigh` as `null`
and maps `high → high`, `max → max`. DeepSeek exposes only off/high/max, and
pi's own docs use `deepseek-v4-pro` as the worked example for exactly this.

**If you are copying a guide written before pi 0.84:** the mapping used to be
`compat.reasoningEffortMap`. pi's docs now say to move it to model-level
`thinkingLevelMap`. Most published DeepSeek-for-pi configs still show the old
field.

### 2. The prefix cache is the whole cost story

DeepSeek bills a cache hit at roughly 1/30th of a miss. pi's default shape —
four tools, append-only transcript — keeps the request prefix byte-identical,
which is why it caches well without being asked to. One published measurement
put pi at a 99.93% hit rate over ~1B input tokens; an eight-harness comparison
on the same model traced the cost spread between harnesses to hit rate rather
than token count.

pi defeats its own cache in two places, and `@rohaquinlop/pi-deepseek-cache`
(installed on first launch, see `packages.txt`) fixes both: it freezes the date
and working directory that pi's system prompt embeds, and makes compaction
deterministic so post-compaction turns still hit. `showCacheMissNotices` is on
in this profile so a miss is visible rather than silent; `/cache-stats` and
`/cache-graph` report the rate.

**The corollary is a rule, not a tip: every tool you add costs cache.** The
tool schema is a fixed block at the front of every request. Four tools is a
block that never changes; forty is a block that changes the moment one is
toggled or reordered. Enable MCP servers and extension tool surfaces per task,
not by default.

### Model choice

`deepseek-v4-flash` is the default, at `high` thinking. Switch to
`deepseek-v4-pro` mid-session with `/model` when a task stalls or needs
multi-step planning — pi swaps models without restarting — and cycle thinking
with Shift+Tab.

This is a judgment call and the published advice genuinely conflicts:
DeepSeek's own recommended mapping puts Pro in the main loop and Flash in
subagents, while the one benchmark with a stated method ran Flash as the main
loop and it came first. Starting cheap and escalating on evidence costs less
than the reverse.

### Cost figures in `models.json` are the peak rate

DeepSeek moved to time-of-day billing on 16 Aug 2026. Peak (01:00–04:00 and
06:00–10:00 UTC) is exactly double off-peak, and pi cannot switch a rate by the
clock, so the profile encodes **peak** — the readout over-reports off-peak
rather than under-reporting peak. European working mornings sit inside the peak
window; long unattended runs are half price outside it.

## The openrouter profile

`./pi.sh --pi-profile openrouter` reaches DeepSeek through one OpenRouter key,
with each model pinned to a different host: **Flash → DigitalOcean**, **Pro →
DeepSeek first-party**. Both carry `allow_fallbacks: false` and
`require_parameters: true`, so a request either goes to the named host or fails
loudly. Unpinned routing is not reproducible — the same slug can be served at a
different quantization, on a different backend, at a different price, and a
benchmark that changed underneath you looks like a model regression.

### Read this before assuming it is cheaper

OpenRouter reports **`supports_implicit_caching: false` for DigitalOcean** — and
for every other third-party host of this model. Only DeepSeek's own endpoint
returns `true`. The `input_cache_read` rate on those hosts is real but is not
automatic prefix caching, so an agent loop re-sending a growing transcript pays
the full input rate on every turn.

That cancels most of the sticker-price win. Per 1M tokens, checked live against
the OpenRouter endpoints API on 2026-08-20:

| | in | out | cache read | implicit cache |
|---|---|---|---|---|
| `digitalocean` (Flash) | $0.068 | $0.168 | $0.0168 | **no** |
| `deepseek` (Flash, off-peak) | $0.22 | $0.66 | $0.007 | **yes** |
| `deepseek` (Pro, off-peak) | $0.66 | $1.98 | $0.022 | **yes** |
| `digitalocean` (Pro) | $0.87 | $1.74 | $0.174 | no |

Worked on a 500K-input / 60K-output task, which is roughly one agentic task's
shape: DigitalOcean Flash costs **$0.044** with no caching; first-party Flash at
99% cache hits costs **$0.044**. A wash off-peak — and first-party doubles at
peak, so DigitalOcean wins there. The tilt is with session length: the longer a
session runs, the more input is re-sent prefix, and the more the cached route
pulls ahead.

Pro is not close. DigitalOcean is more expensive on input, 8× worse on cache
read, and only cheaper on output, which is why Pro is pinned to `deepseek` here.

### Two things worth changing your mind about

**`quantization: "unknown"` on DigitalOcean.** StreamLake ($0.078/$0.157),
Baidu ($0.080/$0.160) and DeepInfra ($0.090/$0.180) all declare fp8 and cost
within 15% on input — StreamLake is *cheaper on output*. Undeclared
quantization is the failure this repo already knows about: an unpinned provider
serving the "same" model differently is what overturned a published result. If
output quality wobbles, repoint `only` at `streamlake` before blaming the model.

**Throughput is unverified.** OpenRouter's `throughput_last_30m` returned 0 for
every provider on this model at time of writing, so per-host tokens/sec could
not be checked. An earlier note in this workspace put DigitalOcean at ~5 tok/s
against DeepSeek's ~74; if that still holds it disqualifies the route for
interactive use regardless of price. Measure it on the first real session.

### Thinking levels differ from the direct profile

OpenRouter takes `reasoning: { effort }`, so this profile exposes `low`,
`medium`, `high` and lets OpenRouter translate onto DeepSeek's off/high/max
ladder. The direct `deepseek` profile addresses those provider levels itself and
exposes `high`/`max` instead. Same models, different control surface.

## Adding a profile

```
dotfiles/pi-profiles/<name>/
  agent/models.json      # optional — provider + model definitions
  agent/settings.json    # optional — defaults
  packages.txt           # optional — pinned `pi install` sources, one per line
  required-env.txt       # optional — variable names to check for (values never printed)
```

Everything under `agent/` is copied into `~/.pi/agent/` on first launch if
absent. Then `./pi.sh --pi-profile <name>`.

Add the profile's API key to the kit's `.env` (or `env.<profile>`) — `claude.sh`
forwards every non-empty variable named there into the container. Never paste a
key into a session; `/login` also works and stores it in the profile.

## Known gaps

- **pi ships no permission system.** Upstream's position is to containerize it,
  which is what this does — but inside the container pi runs unsandboxed, with
  no per-tool approval. `--pi` therefore refuses to run without Docker rather
  than falling back to bare mode.
- **No session adoption or take-back.** Those are Claude Code session
  mechanics; `--pi` exits straight out of the container like `--shell` does.
- **Tool-call reliability with DeepSeek is unmeasured here.** The 400-error
  class is handled by the compat block. How often DeepSeek malforms a tool call
  in normal use is not something this profile can claim either way.
- **`tool_choice`.** oh-my-pi carries a `supportsToolChoice: false` flag for
  DeepSeek's thinking mode. pi 0.84.2's compat table has no such field, so it
  is not set here. If thinking-mode tool calls start returning 400, this is the
  first thing to look at.
