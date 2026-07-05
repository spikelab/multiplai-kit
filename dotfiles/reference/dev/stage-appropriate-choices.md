# Stage-Appropriate Technical Choices

Match technical investment to project maturity. What's right for a weekend POC is wrong for production, and vice versa.

---

## The Core Principle

**Technical choices should scale with project certainty.**

- Low certainty (exploring an idea) → optimize for speed and learning
- High certainty (proven value, scaling) → optimize for reliability and maintainability

Premature optimization wastes time. Under-engineering at scale creates disasters.

---

## Project Stages

### Stage 0: Exploration / Spike

**Goal:** Answer "Is this even possible?" or "Does this approach work?"

**Duration:** Hours to days

**Characteristics:**
- Throwaway code expected
- Single developer
- No users
- Learning and validating assumptions

### Stage 1: Proof of Concept (POC)

**Goal:** Demonstrate feasibility to stakeholders or yourself

**Duration:** Days to 1-2 weeks

**Characteristics:**
- Demo-able but not usable
- Happy path only
- Single developer
- May inform a real project

### Stage 2: Minimum Viable Product (MVP)

**Goal:** Get real user feedback with minimal investment

**Duration:** 2-6 weeks

**Characteristics:**
- Real users (small scale)
- Core functionality works
- Rough edges acceptable
- Small team (1-3 people)

### Stage 3: Production v1

**Goal:** Reliable service for growing user base

**Duration:** Ongoing

**Characteristics:**
- Real users depending on it
- Multiple developers
- Needs to handle failures gracefully
- Data integrity matters

### Stage 4: Scale

**Goal:** Handle significant load and complexity

**Duration:** Ongoing

**Characteristics:**
- Large user base
- Multiple teams
- Performance matters
- Compliance requirements

---

## Choices by Area

### Database

| Stage | Choice | Why |
|-------|--------|-----|
| 0-1 | SQLite or JSON files | Zero ops, instant setup |
| 2 | SQLite or managed Postgres | Still simple, but can grow |
| 3 | Managed Postgres (Supabase, RDS, etc.) | Reliability, backups, connection pooling |
| 4 | Postgres + read replicas, caching layer | Performance at scale |

**SQLite is underrated.** It handles more than people think:
- Single-writer is fine for many apps
- Great for read-heavy workloads
- Perfect for local-first apps
- Litestream can replicate to S3

**When to definitely move to Postgres:**
- Multiple servers writing concurrently
- Need complex queries, full-text search, JSONB
- Concurrent users > hundreds with writes
- Need point-in-time recovery

### Authentication

| Stage | Choice | Why |
|-------|--------|-----|
| 0 | None or hardcoded user | Just get it working |
| 1 | Basic session or single API key | Minimal friction |
| 2 | Simple JWT or session auth | Real but simple |
| 3 | JWT + refresh tokens, proper password handling | Production-ready |
| 4 | OAuth/OIDC, MFA, audit logging | Enterprise requirements |

**Don't build auth from scratch in production.** Consider:
- Clerk, Auth0, Supabase Auth (managed)
- NextAuth.js, Lucia (self-hosted but maintained)

### Error Handling

| Stage | Choice | Why |
|-------|--------|-----|
| 0-1 | Let it crash, print to console | Speed of development |
| 2 | Basic try/catch, user-friendly errors | Don't confuse users |
| 3 | Structured logging, error tracking (Sentry) | Debug production issues |
| 4 | Comprehensive observability, alerting | Proactive issue detection |

### Testing

| Stage | Choice | Why |
|-------|--------|-----|
| 0 | Manual testing only | Throwaway code |
| 1 | Manual + maybe a few critical path tests | Sanity checks |
| 2 | Unit tests for core logic, integration tests for critical paths | Confidence in core |
| 3 | Comprehensive tests, CI/CD, code coverage targets | Prevent regressions |
| 4 | + Load testing, chaos engineering, contract tests | Scale confidence |

**POC testing heuristic:** If you'd cry if it broke, write a test for it.

### Infrastructure

| Stage | Choice | Why |
|-------|--------|-----|
| 0 | Local only | No deployment complexity |
| 1 | Single server (Railway, Render, Fly.io) | One command deploy |
| 2 | PaaS with managed DB | Still simple, more reliable |
| 3 | PaaS or simple IaC, proper environments | Dev/staging/prod separation |
| 4 | Kubernetes, IaC (Terraform), multi-region | Scale and reliability |

**Avoid Kubernetes until you need it.** Signs you might need it:
- Multiple services that need to scale independently
- Team > 10 engineers
- Strict compliance requirements
- Already have k8s expertise

### API Design

| Stage | Choice | Why |
|-------|--------|-----|
| 0-1 | Whatever works, no versioning | Speed |
| 2 | REST-ish, basic validation | Usable by frontend |
| 3 | Proper REST or GraphQL, OpenAPI spec, versioning strategy | Maintainable |
| 4 | + Rate limiting, detailed docs, SDK generation | Developer experience |

### Frontend

| Stage | Choice | Why |
|-------|--------|-----|
| 0 | CLI or Jupyter notebook | No UI complexity |
| 1 | Basic HTML/CSS or Streamlit | Quick visualization |
| 2 | React + Tailwind (simple) | Real but maintainable |
| 3 | React + proper state management, component library | Team scalability |
| 4 | + Design system, accessibility, i18n | Enterprise needs |

### Configuration

| Stage | Choice | Why |
|-------|--------|-----|
| 0-1 | Hardcoded or .env file | Simple |
| 2 | .env + Pydantic settings | Validated, documented |
| 3 | Environment-specific configs, secrets manager | Secure, auditable |
| 4 | + Feature flags, remote config | Dynamic control |

### Logging & Monitoring

| Stage | Choice | Why |
|-------|--------|-----|
| 0-1 | print statements | Quick debugging |
| 2 | structlog or logging module | Searchable logs |
| 3 | Centralized logging, error tracking, basic metrics | Production visibility |
| 4 | Full observability (logs, metrics, traces), dashboards, alerting | Proactive operations |

---

## Anti-Patterns by Stage

### POC Anti-Patterns (Over-Engineering)

- Setting up Kubernetes for a single service
- Building a microservices architecture
- Implementing OAuth before you have users
- Writing comprehensive test suites for exploratory code
- Setting up CI/CD pipelines
- Building an admin dashboard
- Implementing rate limiting
- Using event sourcing or CQRS

### Production Anti-Patterns (Under-Engineering)

- SQLite with multiple concurrent writers
- No error tracking or monitoring
- No backup strategy
- Secrets in code or .env files in production
- No input validation
- No rate limiting on public APIs
- No logging
- Testing in production only

---

## Decision Framework

When choosing a technology or pattern, ask:

### 1. What's the cost of being wrong?

| If wrong means... | Then... |
|-------------------|---------|
| Wasted afternoon | Choose the faster option |
| Wasted week | Think a bit more |
| Months of rework | Invest in the decision |
| Data loss or security breach | Don't cut corners |

### 2. What's the cost of changing later?

| If changing means... | Then... |
|---------------------|---------|
| Find-and-replace | Choose the simpler option now |
| Refactoring a module | Simple is still probably fine |
| Rewriting significant portions | Consider the robust option |
| Data migration with downtime | Get it right now |

### 3. Is this a one-way or two-way door?

**Two-way doors** (easy to reverse): Choose fast, change if needed
- Which HTTP library to use
- Code structure within a service
- Most UI decisions

**One-way doors** (hard to reverse): Think carefully
- Database choice at scale
- Public API contracts
- Authentication architecture
- Data model fundamentals

---

## Upgrade Triggers

### SQLite → Postgres

Move when any of these are true:
- Write contention is causing issues
- Need concurrent writers from multiple servers
- Need complex queries Postgres handles better
- Need row-level locking
- Data > 10GB and need better query optimization

### Simple Auth → Proper Auth

Move when any of these are true:
- Handling real user data
- Compliance requirements (GDPR, SOC2)
- Multiple user roles needed
- Need password reset, email verification
- Security audit requirements

### PaaS → More Control

Move when any of these are true:
- Cost exceeds $1000/month and could be lower
- Need specific infrastructure configurations
- Performance requirements PaaS can't meet
- Compliance requires specific hosting

### Monolith → Services

Move when any of these are true:
- Team > 10 engineers stepping on each other
- Different parts need different scaling
- Different parts have very different deployment cadences
- Clear domain boundaries have emerged

---

## Common Progressions

### Typical Backend Journey

```
Stage 0-1: Python script → FastAPI + SQLite + JSON files
Stage 2:   FastAPI + SQLite + basic JWT + .env
Stage 3:   FastAPI + Postgres + proper auth + structlog + Sentry
Stage 4:   + Redis caching + async workers + k8s + observability stack
```

### Typical Frontend Journey

```
Stage 0:   CLI or curl commands
Stage 1:   HTML + vanilla JS or Streamlit
Stage 2:   React + Tailwind + React Query
Stage 3:   + Component library + proper routing + state management
Stage 4:   + Design system + Storybook + comprehensive testing
```

### Typical Data Journey

```
Stage 0-1: JSON files or SQLite
Stage 2:   SQLite or Postgres
Stage 3:   Postgres + backups + migration strategy
Stage 4:   + Read replicas + connection pooling + caching
```

---

## Summary

| Stage | Optimize For | Accept |
|-------|--------------|--------|
| 0-1 | Learning speed | Technical debt, manual processes |
| 2 | User feedback speed | Rough edges, limited scale |
| 3 | Reliability, maintainability | More complexity, slower iteration |
| 4 | Scale, compliance | Much more complexity, specialized roles |

**The goal is always to build the right thing.** Early stages help you figure out what that is. Later stages help you build it properly.

Don't let perfect be the enemy of good. Don't let good enough be the enemy of necessary.
