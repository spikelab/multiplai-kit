# Getting started with Multiplai

This walks you from nothing to a working setup, then through your first week.
It takes about 20 minutes of attention, most of it waiting.

If you want to know *why* any of this exists, read the
[README](README.md) or the [umbrella repo](https://github.com/spikelab/multiplai).
This file assumes you have decided to try it.

**Contents:** [Before you start](#before-you-start) · [Install](#install) ·
[Your first session](#your-first-session) · [The loop](#the-loop-work-dream-review) ·
[Choosing a memory router](#choosing-a-memory-router) ·
[What runs where](#what-runs-where) · [When something goes wrong](#when-something-goes-wrong)

---

## Before you start

### You need

| | |
|---|---|
| **Claude Code CLI** | `npm install -g @anthropic-ai/claude-code` |
| **A Claude Max plan** *(or an API key)* | Multiplai makes its own Claude calls — routing, diary, learnings. On Max these come out of your rate limit; with an API key they are billed. |
| **Python 3.11+ and [uv](https://docs.astral.sh/uv)** | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **git, jq, ripgrep** | Your package manager has all three. |

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
WORKSPACE=/absolute/path/to/your/workspace   # no ~, no relative paths
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
after every `git pull`.

### Install the skill packs you want

`setup.sh` installs `multiplai-context` — the memory engine, which is the part
that matters. The skill packs are optional and none of them are needed for the
memory loop to work. Install from inside Claude Code with `/plugin`, or from
the shell:

```bash
claude plugin install multiplai-dev@multiplai        # buildme TDD pipeline, skill authoring, code review
claude plugin install multiplai-research@multiplai   # deep research, insight extraction, interviewing
claude plugin install multiplai-writing@multiplai    # writing with your own voice
claude plugin install multiplai-pm@multiplai         # product/PM work
claude plugin install multiplai-media@multiplai      # transcription, YouTube, browser automation
claude plugin install multiplai-messaging@multiplai  # Slack, email
claude plugin install multiplai-apple@multiplai      # Swift / Xcode / iOS
```

Start with none of them. Add one when you hit a task it covers — every pack you
install is more skill descriptions competing for the model's attention.

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
`.multiplai/dreams/applied/`, and your memory directory is a git repository —
the receipt ends with the exact `git revert` that undoes the batch.

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

Measured, not estimated — from one heavy user's own cost ledger, 1,016 router
calls between 2026-08-07 and 2026-08-17 on `claude-haiku-4-5`:

| | |
|---|---|
| Per prompt | **$0.034** mean, $0.024 median |
| Heavy use (~110 prompts/day) | **~$3.80/day**, roughly **$115/month** |
| Light use (~20 prompts/day) | **~$0.70/day**, roughly **$20/month** |

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

To switch, set this in `$CLAUDE_CONFIG_DIR/settings.json`:

```json
{
  "pluginConfigs": {
    "multiplai-context@multiplai": {
      "options": { "memory_router": "llm" }
    }
  }
}
```

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
Your memory directory is a git repo. `git -C <workspace>/.multiplai/memory log`
shows every change; the receipt in `.multiplai/dreams/applied/` names the
commit and the `git revert` to undo it.

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
`setup.sh` falls back to bare mode when Docker is missing or its daemon is
stopped, and says so. Start Docker and re-run `./setup.sh`.

**Health check.** `/multiplai-context:health` reports what is wired up and what
is not. `/multiplai-context:log-doctor` reads the logs when a hook is
misbehaving.

---

## Where things live

Inside the workspace you nominated:

```
.multiplai/
  memory/      your memory files — you edit these, and they are git-tracked
  diary/       per-day narrative, written for you
  learnings/   captured insights waiting to be consolidated
  dreams/      proposals awaiting your review, and applied/ receipts
  data/        catalogs, logs, runtime state
```

`memory/` is the part that is yours. Everything else is machinery.

---

## Keeping current

```bash
cd multiplai-kit
git pull && ./setup.sh
```

`setup.sh` re-checks-out the pinned container version, so a pull that bumps the
container is picked up here and nowhere else. Plugins update separately through
Claude Code's `/plugin` menu.

`CHANGELOG.md` is the only record of what a pull gave you — the kit has no
version tags.
