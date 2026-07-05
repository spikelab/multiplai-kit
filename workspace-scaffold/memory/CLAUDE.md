# Memory File Index

This directory contains Claude's persistent context about you. Each file serves a specific purpose and is routed in automatically by the `multiplai-context` plugin when relevant to a prompt.

## Files

| File | Purpose | When loaded |
|------|---------|-------------|
| `me.md` | Who you are — background, personality, working style | Personal context, relationship questions |
| `technical-pref.md` | Technical preferences — languages, tools, patterns, workflows | Coding tasks, architecture decisions |

## Adding Memory Files

Add new `.md` files here for any topic Claude should remember across sessions. After adding or restructuring files, refresh the catalogs:

```bash
/multiplai-context:refresh-catalogs
```

Good candidates for memory files:
- Career history (for job applications, resume writing)
- Project-specific context (for each major project)
- Writing voice/style guides (for content creation)
- Life context (for personal decisions, relocation planning)
- Financial context (for budget discussions)
