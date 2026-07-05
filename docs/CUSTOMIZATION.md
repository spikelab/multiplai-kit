# Customization Guide

## Personalizing Your Setup

### Memory Files
Your memory files live under `$WORKSPACE/.multiplai/memory/` (also reachable via the `dotfiles/memory/` symlink). Edit these to give Claude persistent context about you:

- `me.md` — Who you are, your background, working style
- `technical-pref.md` — Languages, tools, frameworks, development workflow

Add new memory files for any topic Claude should remember across sessions (career history, project context, writing style, etc.).

Routing and catalog generation are handled by the **`multiplai-context` plugin** — you don't run a generator by hand. After adding or restructuring memory files, refresh the catalogs with:
```bash
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

The `container/` directory provides Docker-based Claude Code:

1. `cp container/.env.example container/.env`
2. Edit `container/.env` with your settings
3. `./container/build.sh` to build the image
4. `./container/dclaude.sh` to launch

The container mounts your workspace and uses the same `CLAUDE_CONFIG_DIR` approach.

## Settings

Edit `dotfiles/settings.json` to customize:
- `env` — Environment variables (token limits, timeouts)
- `permissions.allowedTools` — Auto-approved tools
- `hooks` — Hook registration
- `fileSuggestion` — Custom @ file picker
- `statusLine` — Status bar content
- `enabledPlugins` — LSP plugins

## Reference Docs

Add best-practice docs to `dotfiles/reference/dev/`. Update the reference table in `dotfiles/CLAUDE.md` to tell Claude when to load them.
