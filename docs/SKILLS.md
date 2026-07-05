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
| code-review | Thorough code quality review |
| security-review | Deep security audit |
| deepen | Find module-deepening/refactoring opportunities |
| codebase-walkthrough | Guided codebase exploration |
| e2e-test | End-to-end testing |
| learn-stack | Guided learning for new technologies |
| swift-build | Swift/iOS/macOS builds via the macOS host bridge |
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
| host-browser | Drive the real logged-in Chrome on the macOS host |

### multiplai-context — memory & lifecycle
Namespaced commands: `/multiplai-context:setup`, `:dream`, `:dream-remember`,
`:health`, `:memory-health-audit`, `:now`, `:refresh-catalogs`, `:backfill`.
See the plugin's own README for details.

## Host-bridge requirements

`transcribe`, `youtube-transcript` (audio fallback), `screen-demo`,
`swift-build`, and `host-browser` shell out to the macOS host over SSH and
need `SSH_BUILD_USER`/`SSH_BUILD_KEY` configured in `.env` (see
`.env.example`).
