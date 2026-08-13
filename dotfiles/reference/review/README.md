# Code review checklists

Per-language checklists for reviewing a diff. Six files, 580 lines.

These are a different genre from `reference/dev/`. A doc there is a
**prescriptive standard** — how to build the thing. A doc here is a **review
checklist** — what to look for in a change someone already wrote. That is why
they sit in their own directory instead of being folded in.

## Provenance

Salvaged from `multiplai-dev/skills/code-review/references/` in
`multiplai-cc-mktplace`, which W11 of `plan-buildme-review-hardening-2026-08-11.md`
retires. That skill collided with the Claude Code built-in `/code-review`, and
the built-in cannot load files out of a plugin. These six are the only asset the
built-in has no equivalent for.

Copied verbatim on 2026-08-13. Not rewritten.

## How these get loaded — read this before assuming they work

**Only one of the two reference loaders can see this directory today.**

| Loader | Sees this directory? | Why |
|---|---|---|
| buildme reviewer, via `standards_files` | yes | `_resolve_standards_file` falls back to bare `$CLAUDE_CONFIG_DIR`, so an entry written `reference/review/go-review.md` resolves. `build_pipeline/config.py:724-731` |
| `multiplai-context` per-session pointer block | no | `reference_dir()` returns `base / "reference" / "dev"`, hardcoded. `lib/reference_docs.py:81-84` |

buildme's spec-generation inlining resolves `_DEFAULT_REFERENCE_DOCS` under
`reference/dev/` per its own comment. That resolver has not been read, so treat
it as unconfirmed rather than assume it matches `standards_files`.

**Consequence.** Nothing reaches these files automatically. A buildme project
gets them by naming them in `standards_files`, with the `reference/review/`
prefix. Everything else needs the resolver change tracked in
`multiplai-cc-mktplace` — see the issue linked from that plan.

## The renaming contract applies here too

Once a map names one of these files, it names it as a literal string. Resolution
does no fuzzy matching, and a name with no file on disk is skipped with a log
line, not an error. Renaming a file here after it is registered removes it from
every build while everything continues to look healthy.

## Files

| File | Covers |
|---|---|
| `python-review.md` | Python, FastAPI, Pydantic |
| `javascript-review.md` | JavaScript, TypeScript, React, Node |
| `go-review.md` | Go |
| `c-embedded-review.md` | C, embedded, RTOS |
| `ios-review.md` | iOS, Swift, SwiftUI |
| `valid-patterns.md` | Cross-language. Patterns that look wrong and are not |

`go-review.md`, `c-embedded-review.md` and `valid-patterns.md` have no
equivalent anywhere else in the stack. The other three overlap
`multiplai-dev/skills/deepen/idioms/`, which targets refactor seams rather than
review.
