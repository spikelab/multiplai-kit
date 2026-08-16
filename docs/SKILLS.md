# Skills Reference

Skills ship as **themed plugins** from the Multiplai marketplace
(`spikelab/multiplai-cc-mktplace`). Install the packs you want:

```
/plugin marketplace add spikelab/multiplai-cc-mktplace
/plugin install multiplai-context@multiplai      # memory/context/lifecycle (recommended)
/plugin install multiplai-dev@multiplai          # pick any of the packs below
```

Your own local skills go in `dotfiles/skills/` (`$CLAUDE_CONFIG_DIR/skills/`) —
one directory per skill with a `SKILL.md`. Local skills override plugin skills
of the same name in the routing catalog.

## Invocation

Skills are invoked via slash commands in Claude Code: `/skill-name [args]`.

## The Packs

### multiplai-pm — product management
| Skill | Description |
|-------|-------------|
| pm-jtbd-synthesis | Jobs-to-be-Done synthesis from customer interview transcripts |
| pm-persona-codifier | Codify personas into canonical, source-attributed docs |
| pm-pr-faq | Amazon-style Working Backwards PR/FAQ documents |
| pm-strategy-memo | Minto-Pyramid leadership strategy memos |
| job-application | Tailored resumes and cover letters |
| landing-page | Landing page copy creation and optimization (`create\|audit\|iterate`) |

### multiplai-writing — content creation
| Skill | Description |
|-------|-------------|
| writing | Content toolkit with 6 modes (`brief\|cmd-brief\|draft\|editor\|linkedin\|imagen`) |

### multiplai-research — research & analysis
| Skill | Description |
|-------|-------------|
| deep-research | Code-driven web research pipeline, 20+ sources, three detail levels |
| extract-insights | Deep insight extraction from long-form content (not summarization) |
| interviewer | Ask great questions to uncover assumptions |

### multiplai-dev — development
| Skill | Description |
|-------|-------------|
| buildme | Full bootstrap from idea to working code (spec-driven TDD pipeline) |
| plan | Author a self-contained, executable implementation plan file |
| deepen | Find module-deepening/refactoring opportunities |
| codebase-walkthrough | Guided codebase exploration |
| e2e-test | End-to-end testing |
| learn-stack | Guided learning for new technologies |
| devops-gcp | GCP DevOps workflows |
| skill-creator | Author new skills |
| propose-skill | Formalize repeating patterns into skills |
| analyze-context-router | Audit memory retrieval quality |
| think | Critical thinking audit for conversations |

### multiplai-media — media & host bridge
| Skill | Description |
|-------|-------------|
| transcribe | Transcribe audio with mlx-whisper (host bridge) |
| youtube-transcript | Download YouTube transcripts |
| screen-demo | Turn screen recordings into polished demo videos |
| excalidraw | Generate Excalidraw diagrams |
| host-browser | Drive the real logged-in Chrome on the macOS host (opt-in — see below) |

### multiplai-messaging — Slack, Gmail, meeting transcripts
| Skill | Description |
|-------|-------------|
| slack | Read, search and post to Slack as yourself — your own `xoxp` user token, no bot |
| gmail | Search the inbox, read one message, create a draft. It never sends |
| fireflies | List your Fireflies meetings and pull full transcripts |

Each needs its own credential and nothing else; the setup steps live in the
skill.

### multiplai-apple — Apple platform builds
| Skill | Description |
|-------|-------------|
| swift-build | Swift/iOS/macOS builds via the macOS host bridge |

An explicit add-on pack: `swift-build` used to live in `multiplai-dev` and was
split out so a Linux user is not carrying a macOS-only toolchain skill. The kit
enables it by default because the kit assumes a Mac host.

### multiplai-context — memory & lifecycle
| Skill | Description |
|-------|-------------|
| setup | Onboarding — 2-question quick setup, or `full` for the whole interview |
| dream | Generate a processed-learnings proposal from the pending backlog |
| dream-remember | Review and apply those proposals — the only path that edits memory |
| memory-bank | Shared memory banks: git repos of memory files a team or household shares |
| memory-health-audit | Full audit cross-correlating retrieval logs, diary, learnings and memory files |
| health | Completeness and staleness of memory files, plugin infrastructure, active config |
| config-audit | Subtractive review of the active config, on a ~60-day cadence |
| fleet-status | One ranked snapshot of everything in flight — sessions, PRs, CI |
| costs | API-equivalent cost per chat, skill, subagent, project, model, day |
| log-doctor | Find failures, anomalies and degradation across the runtime logs |
| qmd-search | Search the resources knowledge base via qmd (semantic + keyword) |
| now | Rebuild per-project `now/` status snapshots from recent diary entries |
| backfill | Reconstruct learnings, diary and `now/` from existing session transcripts |
| refresh-catalogs | Regenerate the catalog indexes (`--force`, `--dry-run`, `--only`) |

Skills here are invoked namespaced — `/multiplai-context:dream-remember`,
`/multiplai-context:now`, and so on. See the plugin's own README for details.

## Host-bridge requirements

`transcribe`, `youtube-transcript` (audio fallback), `screen-demo`,
`swift-build`, and `host-browser` shell out to the macOS host over SSH and
need `SSH_BUILD_USER`/`SSH_BUILD_KEY` configured in `.env` (see
`.env.example`).

**`host-browser` needs one thing more: an opt-in on the Mac.** It is the only
bridge tool that reaches your real logged-in Chrome — every cookie, every
signed-in app — so configuring the bridge does not enable it. In container
releases after `v0.9.6` the gateway refuses every `agent-browser` verb unless a
flag file exists:

```bash
mkdir -p ~/.local/state/multiplai
touch ~/.local/state/multiplai/host-browser-enabled     # on
rm ~/.local/state/multiplai/host-browser-enabled        # off
```

Nothing inside a container can create it, which is the point. A blocked session
prints the path and both commands. Full reasoning: [multiplai-container
README](https://github.com/spikelab/multiplai-container#the-host-browser-is-off-by-default).
