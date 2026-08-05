# AI Development Best Practices

Reference documentation for building AI-powered applications with Python (FastAPI, async, MLX), modern frontend (Bun, Vite, React), and Swift/Apple platforms (SwiftUI, macOS, iOS).

---

## Location

These docs live at `$CLAUDE_CONFIG_DIR/reference/dev/` (this directory, symlinked
from the kit's `dotfiles/reference/dev/`).

---

## How these docs get loaded

Three mechanisms, in descending order of how mechanical they are. The first two
are code; the third is a hint and should not be relied on.

### 1. Per-session pointer block — `multiplai-context` (every ordinary session)

The `UserPromptSubmit` hook detects the project's stack from its **manifests**
and injects a `DEV REFERENCES` block naming the matching docs' paths and their
section index — pointers, not contents. Once per session per project.

This is not routed through the memory router, on purpose: memory is context
about *you* and is picked by relevance to your wording, but a standards doc
applies because of what the project **is**. It fires whether or not the prompt
sounds like a coding prompt.

Detection walks up from cwd to the nearest manifest, stopping at `$HOME`. When
cwd is a workspace root holding many repos with no manifest of its own
(`knowhere/PROJECTS/<name>/…`), path-like tokens in the prompt are resolved
instead. Map: `STACK_DOCS` in
`multiplai-context/scripts/lib/reference_docs.py`. Off switch:
`enable_dev_references`.

**Consequence:** if you never name a path and cwd is a bare workspace root,
nothing is detected and nothing is injected. That is the known gap.

### 2. Inlined into spec generation — `buildme` (every build)

A buildme run resolves the same stack→docs mapping and **inlines the contents**
into its spec-generation prompts, because that generator is given no tools and
cannot read a path. A doc over 24000 chars is reduced on section boundaries and
carries an index of every section, so nothing is silently missing. The same docs
also reach the reviewer via `standards_files`, uncapped, and are overridable
per-project with `reference_docs:` in `specs/config.yaml`.

Map: `_DEFAULT_REFERENCE_DOCS` in
`multiplai-dev/skills/buildme/scripts/build_pipeline/config.py`. The run prints
`REFERENCES:<names>` — if that says `(none)` for a project with a real stack,
the specs were written with no conventions to build to.

### 3. The loader table in the global `CLAUDE.md`

A hint to the model, not a mechanism — nothing executes it. Useful for docs no
stack map covers (`prompt-engineering.md`, `stage-appropriate-choices.md`,
`skill-dev.md`, `bruno-api-testing.md`), which is now its actual job.

---

## The renaming contract — read this before renaming a file here

**Two maps live in another repository and name these files as literal strings.**
Resolution does no fuzzy matching, and a name with no file on disk is skipped
with a log line, not an error. So renaming a doc here without updating both maps
**silently removes it from every session and every build**, while everything
continues to look healthy.

This is not hypothetical: `django-best-practices.md` → `django-drf-best-practices.md`
and `react-best-practices.md` → `react-nextjs-best-practices.md` left both keys
resolving nothing from 2026-07 until it was noticed on 2026-08-05.

Renaming or adding a doc that a stack should pick up means editing, in
`multiplai-cc-mktplace`:

| File | Symbol |
|---|---|
| `plugins/multiplai-context/scripts/lib/reference_docs.py` | `STACK_DOCS` |
| `plugins/multiplai-dev/skills/buildme/scripts/build_pipeline/config.py` | `_DEFAULT_REFERENCE_DOCS` |

plus the index table below, and the loader table in `dotfiles/CLAUDE.md`.
`test_builtin_map_names_only_docs_the_kit_actually_ships` (buildme) pins the
current names, so a rename that forgets the map fails a test rather than a build.

A doc that no stack maps to — a process or tooling doc — needs none of this.

### What the stack maps currently say

Both mechanisms use the same key vocabulary and must name the same files:

| Detected in the project | Docs loaded |
|---|---|
| `pyproject.toml` / `requirements.txt` | `uv-python-best-practices.md`, `python-project-structure.md` |
| `manage.py`, or a `django` dependency | `django-drf-best-practices.md` |
| a `fastapi` dependency | `fastapi-best-practices.md` |
| `package.json` | `bun-vite-react-best-practices.md` |
| a `react` or `next` dependency | `react-nextjs-best-practices.md` |
| `Package.swift` | `swift-best-practices.md`, `swift-testing-strategies.md` |
| `Cargo.toml`, `go.mod` | — (no docs written yet) |

Everything else in this directory loads only by mechanism 3 (the model reading
the loader table) or because you ask for it by name. Notably unmapped and worth
knowing about: `database-best-practices.md`, `authentication-best-practices.md`,
`docker-container-patterns.md`, `python-async-llm-patterns.md`,
`data-pipeline-patterns.md`, `swift-macos-best-practices.md`,
`swift-autonomous-tdd.md`.

---

## Document Index

### Python Backend

| Document | Topics |
|----------|--------|
| [uv-python-best-practices.md](./uv-python-best-practices.md) | uv package manager, migration from pip/venv, commands, CI/CD |
| [python-project-structure.md](./python-project-structure.md) | Project layout, src/ structure, Ruff, pragmatic type hints, Pydantic settings, structlog |
| [fastapi-best-practices.md](./fastapi-best-practices.md) | FastAPI patterns, routing, dependencies, async, error handling, testing |
| [python-async-llm-patterns.md](./python-async-llm-patterns.md) | Async patterns, LLM client setup, rate limiting, retries, streaming, concurrent calls |
| [mlx-inference-best-practices.md](./mlx-inference-best-practices.md) | MLX on Apple Silicon, local inference, quantization, memory management |
| [data-pipeline-patterns.md](./data-pipeline-patterns.md) | Chunking, embeddings, batch processing, checkpointing, resumable pipelines |
| [database-best-practices.md](./database-best-practices.md) | SQLite vs Postgres, SQLAlchemy 2.0, migrations, connection pooling, repository pattern |
| [authentication-best-practices.md](./authentication-best-practices.md) | Sessions, JWT, OAuth, password handling, RBAC, API keys, frontend integration |
| [docker-container-patterns.md](./docker-container-patterns.md) | Dockerfiles, layer caching, multi-stage builds, non-root users, compose |
| [prompt-engineering.md](./prompt-engineering.md) | Prompt structure, few-shot, tool use, evaluation, LLM-judge patterns |
| [django-drf-best-practices.md](./django-drf-best-practices.md) | Django 5.2 + DRF monolith: where logic lives, app boundaries, serializers/validation, ORM performance, Celery, Channels, MySQL migration safety, settings, security, caching, testing |

### Frontend

| Document | Topics |
|----------|--------|
| [react-nextjs-best-practices.md](./react-nextjs-best-practices.md) | React 19 + Next.js 15 App Router: server/client boundaries, caching, Server Actions, React Compiler, state management, MUI, auth, testing |
| [bun-vite-react-best-practices.md](./bun-vite-react-best-practices.md) | Bun runtime, Vite setup, React patterns, TypeScript, TanStack Query, Tailwind — client-only SPA, no SSR |

### Swift / Apple Platforms

| Document | Topics |
|----------|--------|
| [swift-best-practices.md](./swift-best-practices.md) | SwiftUI architecture (MV vs MVVM vs TCA), @Observable, Swift 6.2 concurrency, SwiftData, macOS patterns, SPM |
| [swift-macos-best-practices.md](./swift-macos-best-practices.md) | macOS-specific app patterns, windows/menus, sandboxing, entitlements |
| [swift-testing-strategies.md](./swift-testing-strategies.md) | Swift Testing framework, testable architecture, snapshot testing, headless CI, XCUITest, swift-dependencies DI |
| [swift-autonomous-tdd.md](./swift-autonomous-tdd.md) | Autonomous red-green-refactor loop for Swift, headless build/test |

### Architecture & Process

| Document | Topics |
|----------|--------|
| [stage-appropriate-choices.md](./stage-appropriate-choices.md) | POC vs MVP vs Production, when to upgrade, decision framework, anti-patterns |

### Claude Code Tooling

| Document | Topics |
|----------|--------|
| [skill-dev.md](./skill-dev.md) | Building/modifying Claude Code skills — SKILL.md structure, scripts, triggers |
| [hook-writing-patterns.md](./hook-writing-patterns.md) | Writing hooks — event I/O contract, exit codes, deferred work |
| [logging-standard.md](./logging-standard.md) | Shared logging conventions for kit/plugin Python |
| [bruno-api-testing.md](./bruno-api-testing.md) | API testing with Bruno collections, environments, assertions |

---

## Quick Start Patterns

### New Python Project

```bash
# Initialize with uv
uv init myproject
cd myproject

# Add core dependencies
uv add fastapi uvicorn httpx structlog pydantic-settings
uv add --dev pytest ruff

# Set Python version
uv python pin 3.12

# Run
uv run uvicorn src.myproject.main:app --reload
```

### New Frontend Project

```bash
# Create with Bun + Vite
bun create vite my-frontend --template react-ts
cd my-frontend

# Install dependencies
bun add @tanstack/react-query react-router-dom
bun add -d tailwindcss postcss autoprefixer

# Initialize Tailwind
bunx tailwindcss init -p

# Run
bun run dev
```

### Full-Stack AI Project

```
my-ai-app/
├── backend/
│   ├── src/
│   │   └── myapp/
│   │       ├── main.py           # FastAPI
│   │       ├── config.py         # Pydantic settings
│   │       └── features/
│   │           └── chat/
│   │               ├── router.py
│   │               └── service.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   └── features/
│   │       └── chat/
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

---

## Tech Stack Summary

### Backend
- **Runtime**: Python 3.11+
- **Package Manager**: uv
- **Framework**: FastAPI
- **Async HTTP**: httpx
- **Validation**: Pydantic v2
- **Logging**: structlog
- **Linting**: Ruff
- **Testing**: pytest

### Frontend
- **Runtime**: Bun
- **Build Tool**: Vite
- **Framework**: React 19+
- **Language**: TypeScript (strict)
- **Data Fetching**: TanStack Query
- **Styling**: Tailwind CSS

### AI/ML
- **Cloud LLMs**: Anthropic, OpenAI SDKs
- **Local Inference**: MLX (Apple Silicon)
- **Embeddings**: OpenAI, Sentence Transformers
- **Pipelines**: Custom with checkpointing

---

## Key Principles

1. **Consistency**: Use the same patterns across all projects
2. **Type Safety**: Pragmatic Python hints, strict TypeScript
3. **Async First**: Default to async for I/O operations
4. **Resilience**: Built-in retries, rate limiting, checkpointing
5. **Observability**: Structured logging everywhere
6. **Testability**: Dependency injection, mockable clients

---

## Resources

- [uv Documentation](https://docs.astral.sh/uv/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python)
- [MLX Documentation](https://ml-explore.github.io/mlx/)
- [Bun Documentation](https://bun.sh/docs)
- [Vite Documentation](https://vitejs.dev/)
- [TanStack Query](https://tanstack.com/query)
