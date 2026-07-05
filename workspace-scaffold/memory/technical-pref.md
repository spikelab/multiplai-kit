# Technical Preferences

<!-- Fill this in with your technical preferences so Claude can make better recommendations. -->

## Languages & Frameworks

## Development Workflow

## Preferred Patterns

## BuildMe for Coding Projects

For non-trivial implementations (new features, architectural changes, multi-file modifications), use the BuildMe workflow:

```
/buildme
```

BuildMe is a deterministic Python pipeline that handles:
- Artifact generation (proposal → requirements → design → tasks → rubric)
- Model-adaptive TDD implementation
- Scored quality reviews with rubric-based thresholds
- State checkpointing with crash recovery

Artifacts are stored in `specs/` within your project directory.
