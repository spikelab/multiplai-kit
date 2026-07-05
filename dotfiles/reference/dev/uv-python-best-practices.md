# uv Python Package Manager Best Practices

A comprehensive reference for using uv—the fast, all-in-one Python package and project manager.

---

## Table of Contents

1. [Why uv](#1-why-uv)
2. [Installation](#2-installation)
3. [Core Commands](#3-core-commands)
4. [Project Setup](#4-project-setup)
5. [Dependency Management](#5-dependency-management)
6. [Python Version Management](#6-python-version-management)
7. [Running Scripts](#7-running-scripts)
8. [Migration from pip/venv](#8-migration-from-pipvenv)
9. [CI/CD Integration](#9-cicd-integration)
10. [Common Patterns](#10-common-patterns)
11. [Limitations & Gotchas](#11-limitations--gotchas)

---

## 1. Why uv

uv replaces multiple tools with a single, fast binary:

| Traditional Tools | uv Equivalent |
|-------------------|---------------|
| pip | `uv pip` |
| pip-tools | `uv lock` |
| virtualenv/venv | `uv venv` |
| pyenv | `uv python` |
| pipx | `uvx` / `uv tool` |

### Key Benefits

- **Speed**: 10-100x faster than pip for large projects
- **Reliability**: Lockfile-based reproducible builds
- **Simplicity**: Single binary, no dependencies
- **Cross-platform**: Consistent behavior across macOS, Linux, Windows

---

## 2. Installation

```bash
# macOS/Linux (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# With Homebrew
brew install uv

# With pip (if needed)
pip install uv
```

Verify installation:
```bash
uv --version
```

---

## 3. Core Commands

### Quick Reference

```bash
# Project management
uv init myproject          # Create new project
uv add requests            # Add dependency
uv add --dev pytest        # Add dev dependency
uv remove requests         # Remove dependency
uv sync                    # Sync environment to lockfile
uv lock                    # Update lockfile without syncing

# Running code
uv run python main.py      # Run in project environment
uv run pytest              # Run commands in environment

# Python versions
uv python install 3.12     # Install Python version
uv python list             # List available versions
uv python pin 3.12         # Pin version for project

# Tools
uvx ruff check             # Run tool without installing
uv tool install ruff       # Install tool globally

# pip interface (drop-in replacement)
uv pip install requests    # Install package
uv pip install -r requirements.txt
uv pip list                # List installed packages
```

### The Golden Rule

**Replace `python` with `uv run` everywhere.** You never need to manually activate environments or worry about sync:

```bash
# Old way
source .venv/bin/activate
python main.py

# uv way
uv run python main.py
```

---

## 4. Project Setup

### New Project

```bash
uv init myproject
cd myproject
```

This creates:
```
myproject/
├── .git/
├── .gitignore
├── .python-version      # Pinned Python version
├── README.md
├── main.py
└── pyproject.toml
```

### pyproject.toml Structure

```toml
[project]
name = "myproject"
version = "0.1.0"
description = "My project description"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "httpx>=0.27.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.8.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0.0",
    "ruff>=0.8.0",
]
```

### Project Types

```bash
# Application (default)
uv init myapp

# Library (for publishing)
uv init --lib mylib

# Script with inline dependencies
uv init --script analyze.py
```

---

## 5. Dependency Management

### Adding Dependencies

```bash
# Add runtime dependency
uv add requests

# Add specific version
uv add "requests>=2.28.0,<3.0.0"

# Add dev dependency
uv add --dev pytest ruff mypy

# Add from git
uv add git+https://github.com/org/repo.git

# Add optional dependency group
uv add --optional ml torch transformers
```

### Removing Dependencies

```bash
uv remove requests
uv remove --dev pytest
```

### Syncing Environment

```bash
# Sync to match lockfile exactly
uv sync

# Sync including dev dependencies (default)
uv sync --all-extras

# Sync without dev dependencies
uv sync --no-dev

# Upgrade all packages
uv sync --upgrade

# Upgrade specific package
uv sync --upgrade-package requests
```

### Lockfile Management

```bash
# Create/update lockfile
uv lock

# Upgrade all in lockfile (doesn't sync)
uv lock --upgrade

# Check lockfile is up to date
uv lock --check
```

**Important**: `uv lock --upgrade` only updates the lockfile. Use `uv sync --upgrade` to actually install upgraded packages.

---

## 6. Python Version Management

### Installing Python

```bash
# Install specific version
uv python install 3.12

# Install multiple versions
uv python install 3.11 3.12 3.13

# List installed versions
uv python list

# List all available versions
uv python list --all-versions
```

### Pinning Version

```bash
# Pin for current project (creates .python-version)
uv python pin 3.12

# Use specific version for a command
uv run --python 3.11 python script.py
```

### Auto-Download

uv automatically downloads Python if not available:

```bash
# This will download Python 3.12 if needed
uv run --python 3.12 python script.py
```

---

## 7. Running Scripts

### Project Scripts

```bash
# Run in project environment (auto-syncs)
uv run python main.py
uv run pytest tests/
uv run ruff check .
```

### Standalone Scripts with Inline Dependencies

```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "rich",
# ]
# ///

import requests
from rich import print

response = requests.get("https://api.example.com/data")
print(response.json())
```

Make executable and run:
```bash
chmod +x script.py
./script.py
```

### Managing Script Dependencies

```bash
# Add dependencies to script
uv add --script analyze.py pandas matplotlib

# Run script
uv run analyze.py
```

---

## 8. Migration from pip/venv

### Quick Migration

```bash
cd existing-project

# Initialize uv project (won't overwrite existing files)
uv init

# Import existing requirements.txt
uv add -r requirements.txt

# Or import dev requirements separately
uv add --dev -r requirements-dev.txt
```

### Command Mapping

| pip/venv | uv |
|----------|---|
| `python -m venv .venv` | `uv venv` |
| `source .venv/bin/activate` | Not needed with `uv run` |
| `pip install package` | `uv add package` or `uv pip install package` |
| `pip install -r requirements.txt` | `uv pip install -r requirements.txt` |
| `pip freeze > requirements.txt` | `uv pip freeze > requirements.txt` |
| `pip list` | `uv pip list` |
| `pip uninstall package` | `uv remove package` or `uv pip uninstall package` |

### When to Use pip Interface

Use the `uv pip` interface for:
- Quick one-off installs without project structure
- Working with existing requirements.txt workflows
- Compatibility with tools expecting pip

Use the project interface (`uv add/sync/lock`) for:
- New projects
- Reproducible builds with lockfiles
- Long-term maintainable dependencies

---

## 9. CI/CD Integration

### GitHub Actions

```yaml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --all-extras

      - name: Run tests
        run: uv run pytest

      - name: Lint
        run: uv run ruff check .

      # Clean cache for CI (removes unneeded files)
      - name: Prune cache
        run: uv cache prune --ci
```

### Testing Multiple Python Versions

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv python install ${{ matrix.python-version }}
      - run: uv sync
      - run: uv run pytest
```

### Testing Lower Bounds

For libraries, test with minimum versions:

```bash
uv sync --resolution lowest-direct
uv run pytest
```

---

## 10. Common Patterns

### Project with Multiple Entry Points

```toml
# pyproject.toml
[project.scripts]
myapp = "myapp.cli:main"
myapp-server = "myapp.server:run"
```

```bash
uv run myapp
uv run myapp-server
```

### Workspaces (Monorepo)

```
monorepo/
├── pyproject.toml       # Root workspace
├── packages/
│   ├── core/
│   │   └── pyproject.toml
│   └── api/
│       └── pyproject.toml
```

```toml
# Root pyproject.toml
[tool.uv.workspace]
members = ["packages/*"]
```

### Environment-Specific Dependencies

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff"]
docs = ["mkdocs", "mkdocs-material"]
ml = ["torch", "transformers"]
```

```bash
uv sync --extra dev --extra ml
```

---

## 11. Limitations & Gotchas

### Known Limitations

| Limitation | Workaround |
|------------|------------|
| Platform-specific lockfiles | Use `--universal` flag for cross-platform locks |
| Global cache can grow large | Run `uv cache clean` periodically |
| Not all pip features supported | Use `uv pip` for edge cases |
| Still pre-1.0 | Pin uv version in CI |

### Common Gotchas

1. **Lock vs Sync confusion**:
   - `uv lock` only updates the lockfile
   - `uv sync` installs from the lockfile
   - `uv sync --upgrade` does both

2. **Virtual environment location**:
   - Default: `.venv` in project root
   - Override: `UV_PROJECT_ENVIRONMENT` env var

3. **Cache location**:
   - Default: `~/.cache/uv` (Linux/macOS) or `%LOCALAPPDATA%\uv` (Windows)
   - Can grow large with many projects
   - Clean with `uv cache clean`

4. **Python distributions**:
   - uv uses Astral's python-build-standalone
   - Slightly different from official Python in edge cases
   - Use system Python with `--python-preference system` if needed

### Version Pinning for CI

Always pin uv version to avoid surprise breakages:

```yaml
- uses: astral-sh/setup-uv@v4
  with:
    version: "0.5.10"
```

---

## Quick Reference Card

```bash
# Start a project
uv init myproject && cd myproject

# Add dependencies
uv add fastapi uvicorn
uv add --dev pytest ruff

# Run code
uv run python main.py
uv run pytest

# Update dependencies
uv lock --upgrade
uv sync

# Use specific Python
uv python install 3.12
uv python pin 3.12

# Run tools without installing
uvx ruff check .
uvx black .
```

---

## Resources

- [Official Documentation](https://docs.astral.sh/uv/)
- [Migration Guide](https://docs.astral.sh/uv/guides/migration/pip-to-project/)
- [GitHub Repository](https://github.com/astral-sh/uv)
- [Real Python Tutorial](https://realpython.com/python-uv/)
