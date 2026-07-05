# Python Project Structure & Configuration

Best practices for organizing Python projects, configuration management, linting, and pragmatic type hints.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [The src Layout](#2-the-src-layout)
3. [Ruff Configuration](#3-ruff-configuration)
4. [Pragmatic Type Hints](#4-pragmatic-type-hints)
5. [Configuration Management](#5-configuration-management)
6. [Logging with structlog](#6-logging-with-structlog)
7. [Environment Variables](#7-environment-variables)
8. [Complete pyproject.toml Example](#8-complete-pyprojecttoml-example)

---

## 1. Project Structure

### Web Application (FastAPI)

```
myproject/
├── src/
│   └── myproject/
│       ├── __init__.py
│       ├── main.py              # FastAPI app entry point
│       ├── config.py            # Pydantic settings
│       ├── database.py          # DB connection
│       ├── api/
│       │   ├── __init__.py
│       │   ├── routes.py        # Router includes
│       │   └── deps.py          # Shared dependencies
│       ├── features/
│       │   ├── users/
│       │   │   ├── __init__.py
│       │   │   ├── router.py
│       │   │   ├── schemas.py
│       │   │   ├── models.py
│       │   │   ├── service.py
│       │   │   └── exceptions.py
│       │   └── items/
│       │       └── ...
│       └── shared/
│           ├── __init__.py
│           ├── exceptions.py
│           └── middleware.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── pyproject.toml
├── uv.lock
└── README.md
```

### AI/ML Script Project

```
myproject/
├── src/
│   └── myproject/
│       ├── __init__.py
│       ├── main.py              # CLI entry point
│       ├── config.py
│       ├── pipeline/
│       │   ├── __init__.py
│       │   ├── chunking.py
│       │   ├── embedding.py
│       │   └── processing.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── llm_client.py
│       │   └── local_inference.py
│       ├── data/
│       │   ├── __init__.py
│       │   ├── loaders.py
│       │   └── transformers.py
│       └── utils/
│           ├── __init__.py
│           ├── logging.py
│           └── retry.py
├── data/                        # Data directory (gitignored)
│   ├── raw/
│   ├── processed/
│   └── output/
├── notebooks/                   # Exploration (gitignored outputs)
├── tests/
├── pyproject.toml
└── README.md
```

### Standalone Script

For single-file scripts, use inline dependencies:

```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "rich"]
# ///

import httpx
from rich import print

# Script code here
```

---

## 2. The src Layout

### Why src Layout?

1. **Import safety**: Forces installed imports, preventing accidental local imports
2. **Clean packaging**: Only `src/` contents end up in distributions
3. **Test isolation**: Tests import the installed package, not local files

### Setup

```
project/
├── src/
│   └── mypackage/
│       ├── __init__.py
│       └── ...
├── tests/
└── pyproject.toml
```

```toml
# pyproject.toml
[project]
name = "mypackage"

[tool.hatch.build.targets.wheel]
packages = ["src/mypackage"]
```

### Editable Install

For development, install in editable mode:

```bash
uv sync  # Automatically does editable install for project dependencies
```

Or manually:
```bash
uv pip install -e .
```

---

## 3. Ruff Configuration

Ruff is an extremely fast Python linter and formatter. Use it for both linting and formatting (replaces black, isort, flake8).

### Basic Configuration

```toml
# pyproject.toml
[tool.ruff]
line-length = 88
target-version = "py311"

# Exclude common directories
exclude = [
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
]

[tool.ruff.lint]
# Start with these, add more as needed
select = [
    "E",      # pycodestyle errors
    "F",      # pyflakes
    "I",      # isort
    "B",      # flake8-bugbear
    "C4",     # flake8-comprehensions
    "UP",     # pyupgrade
    "ARG",    # flake8-unused-arguments
    "SIM",    # flake8-simplify
]

ignore = [
    "E501",   # Line too long (formatter handles this)
    "B008",   # Do not perform function calls in argument defaults
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]  # Unused imports OK in __init__
"tests/*" = ["ARG"]       # Unused arguments OK in tests

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "auto"
```

### Rule Categories Worth Enabling

| Category | Code | Purpose |
|----------|------|---------|
| pycodestyle | E, W | Style errors and warnings |
| pyflakes | F | Logic errors, undefined names |
| isort | I | Import sorting |
| flake8-bugbear | B | Bug and design problems |
| pyupgrade | UP | Modernize Python syntax |
| flake8-simplify | SIM | Simplify code |
| flake8-comprehensions | C4 | Better comprehensions |

### Running Ruff

```bash
# Lint
uv run ruff check .

# Lint and auto-fix
uv run ruff check --fix .

# Format
uv run ruff format .

# Check formatting without changes
uv run ruff format --check .
```

### Pre-commit Integration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

---

## 4. Pragmatic Type Hints

### Philosophy

Type hints should improve code clarity without hurting readability. Be pragmatic:

- **Always type**: Public API functions, class methods, configuration
- **Usually type**: Internal functions with non-obvious signatures
- **Skip typing**: Obvious cases, quick scripts, exploratory code

### Modern Syntax (Python 3.10+)

```python
# Use | instead of Union
def process(data: str | None) -> dict | None:
    ...

# Use list, dict directly (no List, Dict)
def get_items() -> list[str]:
    ...

def get_mapping() -> dict[str, int]:
    ...
```

### Common Patterns

```python
from collections.abc import Callable, Iterable, Sequence
from typing import Any, TypeVar

# Optional values (can be None)
def find_user(user_id: int) -> User | None:
    """Returns None if not found."""
    ...

# Default None parameter
def search(query: str, limit: int | None = None) -> list[Result]:
    """Limit defaults to 100 if not specified."""
    ...

# Callable types
def retry(func: Callable[..., Any], max_attempts: int = 3) -> Any:
    ...

# TypeVar for generics
T = TypeVar("T")

def first(items: Sequence[T]) -> T | None:
    return items[0] if items else None

# Self-referential types
from typing import Self

class Node:
    def add_child(self, data: str) -> Self:
        ...
        return self
```

### When NOT to Type

```python
# Skip obvious assignments
name = "Alice"           # Clearly a string
count = 0               # Clearly an int
items = []              # Type when appending matters

# Skip simple lambdas
sorted(items, key=lambda x: x.name)

# Skip test functions (usually)
def test_user_creation():
    ...
```

### Type Hints for AI/LLM Code

```python
from typing import Literal, TypedDict

# Structured responses
class LLMResponse(TypedDict):
    content: str
    model: str
    usage: dict[str, int]

# Literal for constrained values
Role = Literal["user", "assistant", "system"]

class Message(TypedDict):
    role: Role
    content: str

# Async generators for streaming
from collections.abc import AsyncGenerator

async def stream_response(prompt: str) -> AsyncGenerator[str, None]:
    async for chunk in client.stream(prompt):
        yield chunk.text
```

---

## 5. Configuration Management

### Pydantic Settings

```python
# config.py
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore unknown env vars
    )

    # App settings
    app_name: str = "myapp"
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./data.db"

    # API keys (no defaults - must be provided)
    anthropic_api_key: str = Field(..., description="Anthropic API key")
    openai_api_key: str | None = None  # Optional

    # Feature flags
    enable_caching: bool = True
    max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance."""
    return Settings()
```

### Domain-Specific Settings

For larger apps, split settings by domain:

```python
# features/llm/config.py
from pydantic_settings import BaseSettings


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_")

    default_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 120


# features/embedding/config.py
class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")

    model_name: str = "text-embedding-3-small"
    batch_size: int = 100
    dimensions: int = 1536
```

### Environment Files

```bash
# .env (gitignored)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
DEBUG=true
DATABASE_URL=sqlite:///./dev.db

# .env.example (committed)
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENAI_API_KEY=sk-your-key-here
DEBUG=false
DATABASE_URL=sqlite:///./data.db
```

---

## 6. Logging with structlog

### Basic Setup

```python
# utils/logging.py
import logging
import sys
import structlog


def configure_logging(json_format: bool = False, level: str = "INFO"):
    """Configure structlog for the application."""

    # Shared processors
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_format:
        # Production: JSON output
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Pretty console output
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


# Auto-detect environment
def setup_logging():
    import os
    use_json = (
        os.getenv("LOG_JSON", "false").lower() == "true"
        or os.getenv("CI", "false").lower() == "true"
        or not sys.stderr.isatty()
    )
    level = os.getenv("LOG_LEVEL", "INFO")
    configure_logging(json_format=use_json, level=level)
```

### Usage

```python
import structlog

logger = structlog.get_logger()

# Simple logging
logger.info("Starting processing")
logger.error("Failed to connect", error=str(e))

# With bound context
log = logger.bind(user_id=123, request_id="abc")
log.info("Processing request")
log.info("Fetching data")  # Includes user_id and request_id

# Temporary context
with structlog.contextvars.bound_contextvars(operation="embedding"):
    logger.info("Generating embeddings", count=100)
```

---

## 7. Environment Variables

### Naming Conventions

```bash
# App-specific prefix
MYAPP_DEBUG=true
MYAPP_DATABASE_URL=...

# Feature-specific prefixes
LLM_DEFAULT_MODEL=claude-sonnet-4-20250514
LLM_MAX_TOKENS=4096
EMBEDDING_MODEL=text-embedding-3-small

# Standard names (no prefix)
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

### .gitignore for Secrets

```gitignore
# Environment files
.env
.env.local
.env.*.local
!.env.example

# Secrets
*.pem
*.key
secrets/
```

---

## 8. Complete pyproject.toml Example

```toml
[project]
name = "myproject"
version = "0.1.0"
description = "My AI project"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Your Name", email = "you@example.com" }]
dependencies = [
    "anthropic>=0.40.0",
    "fastapi>=0.115.0",
    "httpx>=0.27.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.6.0",
    "structlog>=24.4.0",
    "uvicorn>=0.32.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.8.0",
]
ml = [
    "mlx>=0.20.0",
    "mlx-lm>=0.20.0",
]

[project.scripts]
myproject = "myproject.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/myproject"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0.0",
    "ruff>=0.8.0",
]

[tool.ruff]
line-length = 88
target-version = "py311"
exclude = [".git", ".venv", "__pycache__", "build", "dist"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "C4", "UP", "ARG", "SIM"]
ignore = ["E501", "B008"]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]
"tests/*" = ["ARG"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"

[tool.coverage.run]
source = ["src/myproject"]
omit = ["*/tests/*", "*/__pycache__/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

---

## Quick Reference

```bash
# Create project
uv init myproject
cd myproject

# Add dependencies
uv add fastapi uvicorn structlog pydantic-settings
uv add --dev pytest ruff

# Run linting
uv run ruff check .
uv run ruff check --fix .

# Run formatting
uv run ruff format .

# Run with logging
LOG_LEVEL=DEBUG uv run python -m myproject

# Run tests
uv run pytest
uv run pytest --cov
```
