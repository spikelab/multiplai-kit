# Customization Guide

## Personalizing Your Setup

### Memory Files
Your memory files live under `$WORKSPACE/.multiplai/memory/` (also reachable via the `dotfiles/memory/` symlink). Edit these to give Claude persistent context about you:

- `me.md` — Who you are, your background, working style
- `technical-pref.md` — Languages, tools, frameworks, development workflow

Add new memory files for any topic Claude should remember across sessions (career history, project context, writing style, etc.).

Routing and catalog generation are handled by the **`multiplai-context` plugin** — you don't run a generator by hand. After adding or restructuring memory files, refresh the catalogs by running this slash command inside Claude Code:
```
/multiplai-context:refresh-catalogs
```

### Global Instructions (CLAUDE.md)
Edit `dotfiles/CLAUDE.md` to customize Claude's behavior. Your name comes from your memory profile (see Memory Files above), so there are no placeholders to replace. You can further customize:
- Foundational rules and priorities
- Skill trigger conditions
- Reference doc loading rules
- Workspace conventions

### Workspace CLAUDE.md
Edit `$WORKSPACE/CLAUDE.md` for workspace-specific instructions:
- Project registry
- Directory routing rules
- Venv rules for sub-projects

## Adding Skills

1. Create `dotfiles/skills/my-skill/SKILL.md`
2. Follow the skill format (YAML frontmatter + markdown body)
3. Reference helper scripts via `$CLAUDE_CONFIG_DIR/skills/my-skill/scripts/`

Minimal SKILL.md:
```markdown
---
name: my-skill
description: What this skill does and when to use it.
---

# My Skill

Instructions for Claude when this skill is invoked...
```

## Adding Hooks

1. Create your hook in `dotfiles/hooks/`
2. Add it to `dotfiles/settings.json` under the appropriate event
3. Shell hooks: `bash $CLAUDE_CONFIG_DIR/hooks/my-hook.sh`
4. Python hooks: `bash $CLAUDE_CONFIG_DIR/hooks/run-hook-python $CLAUDE_CONFIG_DIR/hooks/my-hook.py`

## Container Mode

The container tooling is fetched into `container/` by `setup.sh` when Docker is
available (from `spikelab/multiplai-container`). You don't launch it directly —
`./claude.sh` runs your session inside the image, mounting your workspace and
using the same `CLAUDE_CONFIG_DIR` approach. To (re)build or reconfigure:

1. Put container settings in the kit-root `.env` (see `.env.example`:
   `WORKSPACE`, `IMAGE_NAME`, `CONTAINER_REF`, host-bridge keys).
2. Re-run `./setup.sh` (or `cd container && ./build.sh`) to build the image.
3. `./claude.sh` to launch a containerized session.

## Settings

Edit `dotfiles/settings.json` to customize:
- `env` — Environment variables (token limits, timeouts)
- `permissions.allowedTools` — Auto-approved tools
- `hooks` — Hook registration
- `statusLine` — Status bar content
- `enabledPlugins` — LSP plugins

An optional `@`-file picker script ships at `dotfiles/scripts/file-suggestion.sh`
but is not registered by default; wire it up under a `fileSuggestion` key in
`settings.json` if you want it.

## Reference Docs

Add best-practice docs to `dotfiles/reference/dev/`.

How they reach Claude depends on whether the doc belongs to a *stack*:

- **Stack- or framework-specific** (a Django doc, a Swift doc) — add it to the
  two stack→filename maps in `multiplai-cc-mktplace` and it loads mechanically:
  the `multiplai-context` hook injects a pointer to it whenever you are in a
  project with that stack, and buildme inlines it into spec generation. Both
  maps and the exact edit are listed in `dotfiles/reference/dev/README.md` →
  "The renaming contract".
- **Cross-cutting** (prompt engineering, architecture staging, tooling) — no map
  applies. Add a row to the reference table in `dotfiles/CLAUDE.md`, which tells
  Claude when to reach for it.

**Renaming an existing doc requires updating those maps.** A name with no file
on disk is skipped with a log line, not an error, so a missed rename removes the
doc from every session and every build while everything still looks fine.
