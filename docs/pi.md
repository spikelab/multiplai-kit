# Running pi in the multiplai container

`pi` and `codex` are on `PATH` in every container session, so a Claude session
can call them as tools. `./pi.sh` also launches the
[pi coding agent](https://pi.dev) as the session itself, inside the same
container `./claude.sh` uses, with the same workspace mounts, git identity, GH
token, env forwarding and SSH host bridge. It is a wrapper around
`claude.sh --pi`, not a second launcher.

```bash
./pi.sh                          # pi, on the one pi config
./pi.sh --profile work           # work git identity, same pi config
./pi.sh -p "summarise this repo" # pi's own flags pass straight through
```

## One config, every provider

Every session mounts one pi config, `~/.claude-container/pi/default` on the
Mac, seeded from `dotfiles/pi-profiles/default/`, and it holds every provider.
The model spec chooses the provider at run time, the way Claude Code chooses
Opus or Sonnet, so there is no second config to switch to.

| Provider | Models | Needs |
|---|---|---|
| `openai` (pi's built-in Sign in with ChatGPT) | your ChatGPT plan's models | a one-time `/login openai` |
| `deepseek` | `deepseek-v4-flash`, `deepseek-v4-pro` | `DEEPSEEK_API_KEY` in `.env` |
| `openrouter` | `deepseek/deepseek-v4-flash`, `deepseek/deepseek-v4-pro`, `z-ai/glm-5.3` | `OPENROUTER_API_KEY` in `.env` |

```bash
pi --provider openai --model <model> -p "…"
pi --provider deepseek --model deepseek-v4-pro -p "…"
pi --provider openrouter --model z-ai/glm-5.3 -p "…"
```

`pi --list-models` prints the exact model IDs each provider offers, including
the ones your ChatGPT plan unlocks.

`z-ai/glm-5.3` is copied from the built-in OpenRouter catalog in
`@earendil-works/pi-ai` 1.2.0, the version pi 1.2.0 depends on. The default
provider and model are DeepSeek V4 Flash.

A missing key is a warning, not an error: it turns off the provider that reads
it and leaves the others working.

### Logging in to ChatGPT

Once, from any session: run `! pi`, then `/login openai`, and choose Sign in
with ChatGPT. The login is stored in the pi config's `agent/auth.json`, which is
`~/.claude-container/pi/default/agent/auth.json` on the Mac, so every later
session has it. pi also writes a `deviceId` into `settings.json`; seeding never
overwrites either file.

### Picking a model per step

buildme and `/multiplai-dev:review` take a `pi:<model>@<provider>` spec
anywhere they take a model, from `multiplai.conf`:

```ini
# buildme: one section per step
[buildme.review]
MODEL=pi:<model>@openai

[buildme.spec]
MODEL=pi:z-ai/glm-5.3@openrouter

# /multiplai-dev:review: top-level keys
review_finder_model=pi:deepseek-v4-flash@deepseek
review_verifier_model=pi:deepseek-v4-pro@deepseek
```

buildme reads `[buildme.spec]`, `[buildme.agent]`, `[buildme.plan_review]` and
`[buildme.review]`. Replace `<model>` with an ID from `pi --list-models`.

## What the pi config is

The whole `~/.pi` directory: `models.json`, credentials, installed packages,
and session history, mounted from `~/.claude-container/pi/default` on the Mac.
pi reads its config from `~/.pi/agent` unless `PI_CODING_AGENT_DIR` is set (pi
1.2.0 `docs/environment-variables.md`), and the container does not set it for
sessions. `--profile <name>` picks a git identity and GH token from
`env.<name>`; it never changes the pi config.

The template under `dotfiles/pi-profiles/default/` is in git and is only ever
copied into the live directory when a file is *absent*. `claude.sh` does that
copy on the Mac before every container launch, so a plain Claude session gets a
ready `~/.pi`; `scripts/pi-bootstrap.sh` does it again under `--pi`. Anything
you or pi subsequently write — `/settings`, `pi install`, `/login` — wins over
the template and survives the next launch.

The packages in `packages.txt` cannot be copied: `pi install` has to run inside
the container, where pi is. So every container session installs them, not only
`--pi`. A plain claude, `--shell` or driver launch starts its command behind
`scripts/pi-bootstrap.sh --packages-only --`, which installs the lists when they
changed (see [Web search](#web-search)) and then runs claude, bash or the
driver runner as before; `--pi` runs the whole bootstrap, packages included. So
`pi` called as a tool from a Claude session (`pi:<model>@<provider>` in a
buildme or `/multiplai-dev:review` step) has web search and the DeepSeek cache
fix too.

## How pi and Codex get into the container

The same way Claude Code does: a pinned copy baked into the image as the
fallback, and a copy in a folder mounted from the Mac that the container
entrypoint keeps current.

| | pi | Codex |
|---|---|---|
| Mac folder | `~/.claude-container/pi-cli` | `~/.claude-container/codex` |
| Container path | `~/.pi-cli` | `~/.codex` (releases and login) |
| Binary, first on `PATH` when present | `~/.pi-cli/agent/bin/pi` | `~/.codex/bin/codex` |
| Installed by | `https://pi.dev/install.sh` | `https://chatgpt.com/codex/install.sh` |
| Weekly update | `pi update` | the installer again |

The entrypoint updates each one every `MULTIPLAI_CLI_UPDATE_DAYS` (default 7),
the interval it already uses for Claude Code, so a new release reaches every
session within a week with no image rebuild. If an install or update fails, the
session starts anyway on the copy it already has, or on the baked one.
`claude.sh` mounts all three folders (`pi-cli`, `pi/default`, `codex`) in
every container session: plain claude, `--shell`, `--pi` and the hub driver.

The bootstrap no longer installs pi, and `MULTIPLAI_PI_VERSION` is gone.

## Codex

Codex is for ad hoc reviews through OpenAI's Claude Code plugin. Once, from any
session:

1. Run `codex login`. If the browser callback cannot reach the container, use
   Codex's device-code login instead.
2. In Claude Code, run `/plugin marketplace add openai/codex-plugin-cc`, then
   `/plugin install codex@openai-codex`.

The login lives in `~/.claude-container/codex` on the Mac, so later sessions
keep it. Then `/codex:review` runs a review.

## The deepseek provider

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
(installed by the first container launch of any kind, see
`default/packages.txt`) fixes both: it freezes
the date and working directory that pi's system prompt embeds, and makes
compaction deterministic so post-compaction turns still hit.
`showCacheMissNotices` is on so a miss is visible rather than silent;
`/cache-stats` and `/cache-graph` report the rate. It activates on `deepseek-*` model ids; whether it also matches
the `openrouter` provider's `deepseek/…` ids is unverified, and `/cache-stats`
reporting nothing there would mean it does not.

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
clock, so `models.json` encodes **peak** — the readout over-reports off-peak
rather than under-reporting peak. European working mornings sit inside the peak
window; long unattended runs are half price outside it.

## The openrouter provider

The `openrouter` provider reaches DeepSeek through one OpenRouter key (and
GLM 5.3 through the same key), with each DeepSeek model pinned to a different
host: **Flash → DigitalOcean**, **Pro →
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

### Thinking levels differ from the direct provider

OpenRouter takes `reasoning: { effort }`, so this provider exposes `low`,
`medium`, `high` and lets OpenRouter translate onto DeepSeek's off/high/max
ladder. The direct `deepseek` provider addresses those provider levels itself and
exposes `high`/`max` instead. Same models, different control surface.

## Web search

pi ships **no web access at all** — no search, no URL fetch. That is the largest
single gap against Claude Code, and it is not a setting you can turn on; it
arrives as a package.

`dotfiles/pi-profiles/_shared/packages.txt` is installed before
`default/packages.txt`, and web search is what it is there for. It brings
four tools — `web_search`, `fetch_content` (URL to markdown, also PDFs),
`source_check` (claims with passage citations), `get_search_content` — plus
`/websearch` and `/search`.

No extra configuration: the extension reads provider keys straight from the
environment, so `EXA_API_KEY` and `TAVILY_API_KEY` in the kit's `.env` are
already forwarded and already picked up. It walks a fallback chain and stops at
the first provider that answers. Without any key it can still reach Exa's hosted
MCP endpoint — but note that queries then go to a third party under no account
of yours, which is a reason to prefer your own key rather than a fallback.

Adding a line to either `packages.txt` reaches a config that has **already**
launched. The marker, `~/.pi/agent/.multiplai-packages-installed`, records a
hash of the combined list rather than a bare "ran once" flag, so a changed list
re-runs on the next container launch of any kind; `pi install` is idempotent.
While the hash matches, the launch only reads the marker. A package that fails
to install leaves the marker unwritten, so a transient npm failure retries next
launch instead of being silently marked done.

Outside `--pi`, a failed install never stops the session. No network, no `pi`
in the container yet, or an npm error prints one `[pi] Warning:` line naming
the cause, and claude, bash or the driver runner starts anyway, with pi lacking
those packages until a later launch installs them. `pi install`'s own output
goes to `~/.pi/agent/.multiplai-packages.log`, since the terminal belongs to the
session about to start. The session waits for the install while it runs, which
happens only on a launch where the list changed. Under `--pi` the install
prints each package and each failure in the terminal, as before.

**Two cautions.** pi's own docs are blunt that packages run with full system
access and extensions execute arbitrary code — the container is the only thing
between that and your machine, which is another reason `--pi` refuses to run
without Docker. And several unrelated GitHub projects share the name
`pi-web-access`; the pinned one is the package published to npm,
[nicobailon/pi-web-access](https://github.com/nicobailon/pi-web-access).

### GitHub cloning is off, deliberately

`_shared/web-search.json` ships `{"githubClone": {"enabled": false}}`, seeded to
`~/.pi/web-search.json`. That path is not decorative — the
extension resolves its config to `~/.pi/web-search.json` unless
`PI_CODING_AGENT_DIR` or `XDG_CONFIG_HOME` is set, and neither is set in this
container.

The clone path in 0.24.0 will delete a directory you did not name.
`decodeURIComponent` is applied to each path segment of a github.com URL with no
character-set check, so `%2E%2E%2F` becomes `../`; the decoded owner segment is
joined into the clone destination with no containment check; and the destination
is `rmSync`'d recursively *before* the clone runs. The host check passes because
the host really is github.com.

**The container does not contain this.** The workspace is bind-mounted at the
same absolute path inside and out, so a delete under `/Users/…` from in here
removes the real file. And the trigger is the agent fetching a crafted link —
precisely what a web-search extension does with links it finds, so an attacker
needs only a page the agent reads.

`enabled: false` is checked at the top of the clone entry point, before any path
is built or removed, and returns `null` rather than throwing.

**What it costs:** no repository cloning. GitHub reading through the API is a
separate module with no reference to this gate, so issues, READMEs and file
contents still work. For an actual checkout use `git clone` or `gh repo clone`
from pi's bash tool — that is you naming a repo, not a URL the agent happened to
read, which is the whole difference.

Re-enable only once upstream has fixed the traversal.

## Adding a provider

Add it to `models.json` in two places: `dotfiles/pi-profiles/default/agent/`
for new installs, and `~/.claude-container/pi/default/agent/` on the Mac for
yours. Seeding copies a file only when it is absent, so a template edit never
reaches a config that already has a `models.json`. Name its key variable in
`dotfiles/pi-profiles/default/required-env.txt` so a missing key is reported.

Add the provider's API key to the kit's `.env` (or `env.<profile>`) — `claude.sh`
forwards every non-empty variable named there into the container. Never paste a
key into a session; `/login` also works and stores it in the pi config.

## Known gaps

- **pi ships no permission system.** Upstream's position is to containerize it,
  which is what this does — but inside the container pi runs unsandboxed, with
  no per-tool approval. `--pi` therefore refuses to run without Docker rather
  than falling back to bare mode.
- **No session adoption or take-back.** Those are Claude Code session
  mechanics; `--pi` exits straight out of the container like `--shell` does.
- **Tool-call reliability with DeepSeek is unmeasured here.** The 400-error
  class is handled by the compat block. How often DeepSeek malforms a tool call
  in normal use is not something this config can claim either way.
- **`tool_choice`.** oh-my-pi carries a `supportsToolChoice: false` flag for
  DeepSeek's thinking mode. pi 0.84.2's compat table has no such field, so it
  is not set here. If thinking-mode tool calls start returning 400, this is the
  first thing to look at.
