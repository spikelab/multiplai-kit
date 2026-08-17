# Getting started with Multiplai

This walks you from nothing to a working setup, then through your first week.
It takes about 20 minutes of attention, most of it waiting.

If you want to know *why* any of this exists, read the
[README](README.md) or the [umbrella repo](https://github.com/spikelab/multiplai).
This file assumes you have decided to try it.

**Contents:** [Before you start](#before-you-start) · [Install](#install) ·
[Your first session](#your-first-session) · [The loop](#the-loop-work-dream-review) ·
[Choosing a memory router](#choosing-a-memory-router) ·
[What runs where](#what-runs-where) · [When something goes wrong](#when-something-goes-wrong) ·
[Where things live](#where-things-live) · [Keeping current](#keeping-current)

---

## Before you start

### You need

| | |
|---|---|
| **Claude Code CLI** | `npm install -g @anthropic-ai/claude-code` |
| **A Claude Max plan** *(or an API key)* | Multiplai makes its own Claude calls — routing, diary, learnings. On Max these come out of your rate limit; with an API key they are billed. |
| **Python 3.12+ and [uv](https://docs.astral.sh/uv)** | `curl -LsSf https://astral.sh/uv/install.sh \| sh`. uv fetches its own interpreter if yours is older. |
| **git, jq, curl** | Setup stops without them. |
| **ripgrep** *(optional)* | Setup warns and carries on. |

### You want

**Docker or [OrbStack](https://orbstack.dev).** Multiplai runs Claude inside a
container by default, which is what makes it safe to run with
`--dangerously-skip-permissions` — the agent can move freely inside a sandbox
instead of asking you to approve every file write. Without Docker it still
works, but Claude runs directly on your machine with no sandbox. On macOS,
prefer OrbStack: some networking conveniences are OrbStack-specific and noted
where they matter.

**ffmpeg**, if you want the transcription skills.

### Pick your workspace directory first

Multiplai keeps all its state — your memory files, session diaries, captured
learnings — in a `.multiplai/` directory inside a workspace you nominate. Point
it at a directory **you already work in and back up**, not a scratch path. Your
memory files are the part that becomes valuable, and moving them later is
annoying.

---

## Install

```bash
git clone https://github.com/spikelab/multiplai-kit
cd multiplai-kit

cp .env.example .env
```

Open `.env` and set three things:

```sh
WORKSPACE=/absolute/path/to/your/workspace   # absolute, or a leading ~
GIT_AUTHOR_NAME="Your Name"
GIT_AUTHOR_EMAIL=you@example.com
```

Then:

```bash
./setup.sh
```

That runs eight steps: it creates the workspace directories, lays down memory
templates, writes a workspace `CLAUDE.md`, builds a Python environment, links
config, seeds Claude Code settings, points the plugin at your workspace, and
installs the Multiplai plugins from the marketplace. It also fetches the
container image if Docker is running.

**`setup.sh` is safe to re-run.** It skips what already exists. Run it again
after every pull — and see [Keeping current](#keeping-current) for why the pull
itself needs one extra step.

### Install the skill packs you want

`setup.sh` installs `multiplai-context` — the memory engine, which is the part
that matters. The skill packs are optional and none of them are needed for the
memory loop to work.

**Install them from inside a session**, with `/plugin`:

```
/plugin install multiplai-dev@multiplai        # buildme TDD pipeline, skill authoring, planning
/plugin install multiplai-research@multiplai   # deep research, insight extraction, interviewing
/plugin install multiplai-writing@multiplai    # writing with your own voice
/plugin install multiplai-pm@multiplai         # product/PM work
/plugin install multiplai-media@multiplai      # transcription and YouTube; browser automation is macOS-only
/plugin install multiplai-messaging@multiplai  # Slack, email
/plugin install multiplai-apple@multiplai      # Swift / Xcode / iOS — macOS only
```

**Not from a plain shell — at least, not without a prefix.** The kit
deliberately does not touch your `~/.claude`: it sets `CLAUDE_CONFIG_DIR` to
its own `dotfiles/` directory, and that is where the marketplace is
registered. A bare `claude plugin install multiplai-dev@multiplai` in your
own shell fails with *"Plugin not found in marketplace"*, and its suggested
remedy (`marketplace update`) is the wrong one. If you want the shell form:

```bash
CLAUDE_CONFIG_DIR=/path/to/multiplai-kit/dotfiles \
  claude plugin install multiplai-dev@multiplai
```

Start with none of them. Add one when you hit a task it covers — every pack you
install is more skill descriptions competing for the model's attention. (The
kit ships all seven marked enabled, so they appear in `/plugin` immediately;
enabled is not installed, and an uninstalled pack costs you nothing.)

---

## Your first session

```bash
./claude.sh
```

**First launch asks you to authenticate.** Run `/login` and follow the prompt.
Credentials persist across container restarts.

### Wait for the environment to finish building

The first time a hook fires, the plugin builds its Python environment in the
background. **Until that finishes, the memory hooks are deliberately inert** —
they gate themselves rather than fail half-built. On a cold install this can
take a few minutes, and the gate holds for up to 15.

You do not have to sit through it. The next step clears it.

### Run the setup interview

```
/multiplai-context:setup
```

Two questions — what to call you, and where state should live — then it writes
your memory templates. About two minutes. It warms the plugin environment
first, which is what releases the gate above, so run this before anything else
even if you plan to skip the questions.

There is a longer version, `/multiplai-context:setup full`, that adds a
three-phase interview about how you work. You can run it any time; it deepens
what the quick path started. Most people should do the quick one now and the
full one after a week, when they have opinions.

### Then just work

Open a real task. Nothing else needs configuring.

---

## The loop: work, dream, review

This is the whole system, and it is three steps.

### 1. You work. Capture happens on its own.

Every session writes a **diary** entry — what happened and why — to
`.multiplai/diary/YYYY-MM-DD.md`, and extracts **learnings** to
`.multiplai/learnings/`. You do nothing. This is the part that is normally too
tedious to sustain, and it is automated precisely because it is.

Meanwhile, each prompt you send is **routed**: the relevant memory files are
selected and injected as context. Week 40 knows what week 1 learned.

### 2. `/multiplai-context:dream` proposes what to remember.

Learnings pile up. Dream reads the backlog and writes a **proposal** — grouped
by which memory file each item belongs in, with the source citation for every
claim — to `.multiplai/dreams/`. It runs a few minutes and makes no changes to
your memory.

Run it when the backlog has built up. Weekly is a reasonable rhythm.

### 3. `/multiplai-context:dream-remember` is where you hold the pen.

This is the step the whole design exists to protect. It walks the proposal,
applies what is uncontroversial, and **asks you about the rest**.

Two things it will never write without you saying so:

- **Anything that is a rule rather than a fact.** A wrong fact is one you
  notice later; a wrong rule changes what you notice. So rules wait for you,
  every time, under every setting.
- **Anything targeting a `CLAUDE.md`.** Refused in code, in every mode.

Everything it does apply lands in a **receipt** under
`.multiplai/dreams/applied/`, naming every file it touched.

**Make your memory directory a git repository before you rely on undo.**
Neither `setup.sh` nor the quick setup does this for you — it is an opt-in
offer in the *full* interview (`/multiplai-context:setup full`). Without it
the receipt tells you what changed but you have no way back. One command,
worth running today:

```bash
git -C <workspace>/.multiplai/memory init && \
  git -C <workspace>/.multiplai/memory add -A && \
  git -C <workspace>/.multiplai/memory commit -m "baseline"
```

**Keep the backlog small.** A proposal of 200+ items is not reviewable in one
sitting, and an unreviewed proposal is the failure mode this system has to
avoid. Running dream weekly on 30 items is far better than monthly on 200.

---

## Choosing a memory router

The router decides which memory files get injected into each prompt. There are
two, and **the kit ships the cheaper one by default.**

| | `token_overlap` *(default)* | `llm` |
|---|---|---|
| How | Lexical scoring, offline | A Haiku call per prompt |
| Cost | **Nothing** | See below |
| Accuracy | F1 **20.0** | F1 **48.6** |

Both numbers come from the same backtest: 300 real prompts drawn from 273 chats
over 21 days, scored against a hindsight oracle. `llm` is **2.4× better** and
injects fewer bytes while doing it.

### What `llm` actually costs

Measured, not estimated — from one heavy user's own cost ledger, over 1,000
router calls between 2026-08-07 and 2026-08-17 on `claude-haiku-4-5`:

| | |
|---|---|
| Per prompt | **$0.035** mean, $0.025 median |
| Heavy use (~110 prompts/day) | **~$3.85/day**, roughly **$115/month** |
| Light use (~20 prompts/day) | **~$0.70/day**, roughly **$21/month** |

Read those as **API-equivalent** figures. On a Max plan these calls consume
your rate limit rather than billing you; the dollar amounts tell you the
*size* of what you are spending, in the units everyone understands.

The cost is dominated by cache writes — about 12,400 tokens written per call
against only ~1,900 read back, because the cache expires between prompts.
That is a known inefficiency, not an inherent price.

### Which to pick

**Start on `token_overlap`.** It is free, it is the default, and for the first
week your memory files are mostly templates — there is little for a smarter
router to be smarter about.

**Switch to `llm` once your memory is real** and you notice the wrong files
being injected, or the right ones missing. That is the symptom it fixes, and
by then you will have the usage numbers to price it against your own volume.

To switch, **add one line** to the existing `options` block in
`$CLAUDE_CONFIG_DIR/settings.json` — which for a kit install is
`multiplai-kit/dotfiles/settings.json`:

```json
"memory_router": "llm"
```

so that the block reads something like:

```json
{
  "pluginConfigs": {
    "multiplai-context@multiplai": {
      "options": {
        "workspace_dir": "/your/workspace",
        "skills_dir": "",
        "resources_dir": "",
        "memory_router": "llm"
      }
    }
  }
}
```

**Merge, do not replace.** `setup.sh` writes `workspace_dir` into that same
`options` object, and pasting a document that contains only `memory_router`
deletes it. Nothing errors — your memory silently relocates to the default
directory and the files you have been building stop being read.

The key must be the compound `multiplai-context@multiplai` form. A bare
`multiplai` key **fails silently** — Claude Code ignores it and every option
falls back to its default.

---

## What runs where

### macOS

The best-supported path. Use OrbStack rather than Docker Desktop: container
hostnames resolve as `<name>.orb.local` from the Mac with no port publishing,
and a couple of conveniences depend on OrbStack's loopback routing.

macOS also gets an opt-in bridge that lets a session run a small allowlist of
tools on the host — Xcode builds, browser automation, local transcription.
Everything else works without it.

**The bridge is write-jailed to the workspace you nominated.** `setup.sh`
records that path on the host and installs a sandbox profile alongside it, so
a bridge command cannot write outside it. The container never supplies the
boundary — a limit set by the thing being confined is not a limit. Two
consequences worth knowing: the jail restricts *writes* only, so anything
running under it can still read host files including credentials; and the
declaration is per machine, so if you run two kits the last `./setup.sh` wins
and the earlier workspace stops being writable from the bridge.

### Linux

Fully supported and the most heavily tested path in CI. No host bridge — there
is nothing on a Linux host that a container needs to reach out for. Use Docker
or Podman.

**Not Docker Desktop for Linux.** Its VM indirection breaks the loopback
bridging some features assume. Install the Docker engine directly.

### Windows via WSL2

Runs the Linux path from inside your WSL2 distribution — clone, configure and
launch there, not from PowerShell.

Two honest caveats. The host-side helpers are macOS-only by design, so you get
no host bridge — no host browser automation, no Keychain credential lookup, no
Xcode anything. None of that affects the memory system, which is the reason to
use Multiplai. And **this path has had less real-world use than the other two**;
if you hit something, it is worth reporting rather than assuming you did it
wrong.

---

## When something goes wrong

**Nothing is being captured — no diary, no learnings.**
The plugin environment is probably still building, or its gate never cleared.
Run `/multiplai-context:setup` (it warms the environment as its first step). If
that fails, `uv` is likely missing or not on PATH.

**A memory file was updated and it should not have been.**
The receipt in `.multiplai/dreams/applied/` names every file the batch
touched. If you made the memory directory a git repository (see
[the dream-remember step](#3-multiplai-contextdream-remember-is-where-you-hold-the-pen)),
`git -C <workspace>/.multiplai/memory log` shows each change and `git revert`
undoes it. If you did not, the receipt is all you have — which is the reason
to do it now rather than after the first bad write.

**The wrong memory files keep getting injected.**
Expected on `token_overlap` once your memory grows — see
[Choosing a memory router](#choosing-a-memory-router).

**Plugins did not install during setup.**
`setup.sh` skips this silently if you were offline or not yet logged in. From
inside Claude Code:

```
/plugin marketplace add spikelab/multiplai-cc-mktplace
/plugin install multiplai-context@multiplai
```

**Claude is running without a sandbox and you did not expect that.**
`setup.sh` falls back to bare mode when Docker is **not installed**, and says
so. Install Docker or OrbStack and re-run `./setup.sh`.

**`./claude.sh` refuses to launch and names the Docker daemon.**
Different case, deliberately. A stopped daemon is not a missing one, so
neither script guesses: setup declines to configure bare mode and the launcher
exits rather than dropping you into an unsandboxed session you did not ask
for. Start Docker, or run `./claude.sh --local` if you genuinely want this one
session outside the container.

**Health check.** `/multiplai-context:health` reports what is wired up and what
is not. `/multiplai-context:log-doctor` reads the logs when a hook is
misbehaving.

---

## Where things live

Inside the workspace you nominated:

```
.multiplai/
  memory/      your memory files — the ones you edit
  diary/       per-day narrative, written for you
  learnings/   captured insights waiting to be consolidated
  now/         per-project status snapshots, injected at session start
  dreams/      proposals awaiting your review, and applied/ receipts
               (created by the first dream run, not by setup)
  data/        catalogs, logs, runtime state
```

`memory/` is the part that is yours. Everything else is machinery.

---

## Keeping current

```bash
cd multiplai-kit
git pull && ./setup.sh
```

**That plain `git pull` will eventually refuse**, and it is not your mistake.
`dotfiles/settings.json` is tracked, and `setup.sh` writes your plugin options
into it on every run — so a configured checkout always has one modified file.
The moment an upstream commit touches that same file, git aborts with *"Your
local changes would be overwritten by merge"*. Upstream touches it every week
or two. The way through:

```bash
git stash push dotfiles/settings.json
git pull --rebase origin main
git stash pop
./setup.sh
```

If `git stash pop` reports a conflict, keep your own values for the options
`setup.sh` writes (`workspace_dir`, `skills_dir`, `resources_dir`) and take
upstream's for everything else.

`setup.sh` re-checks-out the pinned container version, so a pull that bumps the
container is picked up here and nowhere else. Plugins update separately through
Claude Code's `/plugin` menu.

`CHANGELOG.md` is the only record of what a pull gave you — the kit has no
version tags.
