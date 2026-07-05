# AI Development Best Practices

Reference documentation for building AI-powered applications with Python (FastAPI, async, MLX), modern frontend (Bun, Vite, React), and Swift/Apple platforms (SwiftUI, macOS, iOS).

---

## Location

These docs live at `$CLAUDE_CONFIG_DIR/reference/dev/` and are indexed in the global CLAUDE.md.

Claude Code agents automatically load relevant docs based on task triggers defined in the global CLAUDE.md.

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

### Frontend

| Document | Topics |
|----------|--------|
| [bun-vite-react-best-practices.md](./bun-vite-react-best-practices.md) | Bun runtime, Vite setup, React patterns, TypeScript, TanStack Query, Tailwind |

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
