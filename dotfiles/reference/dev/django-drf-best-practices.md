# Django + DRF Best Practices

Production patterns for a Django 5.1/5.2 monolith serving a JSON API to a separate
JavaScript frontend, with Celery, Channels, Redis and MySQL 8.

Companion doc: [react-nextjs-best-practices.md](./react-nextjs-best-practices.md).
The two share [§14 The API contract seam](#14-the-api-contract-seam).

**Version anchor:** Django 5.2 LTS, DRF 3.16, Celery 5.4+, Channels 4.x, MySQL 8.
Where behaviour changed between versions, the version is named inline. Prefer
`docs.djangoproject.com/en/5.2/` over `/stable/` when checking a claim — `/stable/`
silently renders the newest release.

---

## Table of Contents

1. [Where business logic lives](#1-where-business-logic-lives)
2. [App boundaries and how to enforce them](#2-app-boundaries-and-how-to-enforce-them)
3. [DRF: views, serializers, validation](#3-drf-views-serializers-validation)
4. [ORM performance discipline](#4-orm-performance-discipline)
5. [Celery in production](#5-celery-in-production)
6. [Channels and websockets](#6-channels-and-websockets)
7. [Async Django: when it actually helps](#7-async-django-when-it-actually-helps)
8. [Migrations and schema safety on MySQL](#8-migrations-and-schema-safety-on-mysql)
9. [Settings, configuration, secrets](#9-settings-configuration-secrets)
10. [Security](#10-security)
11. [Caching](#11-caching)
12. [Logging and observability](#12-logging-and-observability)
13. [Testing](#13-testing)
14. [The API contract seam](#14-the-api-contract-seam)
15. [Review checklist](#15-review-checklist)

---

## 1. Where business logic lives

This is the one genuinely contested question in the Django community, so it gets
answered first — everything else follows from it.

### The two camps

| | **Service layer** | **Fat models** |
|---|---|---|
| Advocates | [HackSoft Styleguide](https://github.com/HackSoftware/Django-Styleguide), [David Seddon](https://seddonym.me/2018/09/16/rocky-river-pattern/), [cosmicpython](https://www.cosmicpython.com/book/appendix_django.html) | [James Bennett](https://www.b-list.org/weblog/2020/mar/16/no-service/) |
| Logic lives in | per-app `services.py` (writes) + `selectors.py` (reads) | model methods + custom `Manager`/`QuerySet` |
| Argument | logic spanning multiple models has no natural model home; explicit call sites make data flow traceable | a service layer fights Django's Active-Record ORM and amounts to "your own private ORM"; spend the complexity budget elsewhere |

Bennett does **not** name HackSoft — this is a topical disagreement about a
pattern, not a feud. Both positions are argued by reputable people and neither
has won.

### The default to apply

**Single-model logic goes on the model or its manager/queryset. Logic that spans
several models, or that orchestrates a write plus a side effect (email, Celery
task, external API), goes in a service function.**

That splits the difference deliberately, and it is the position both camps can
live with: it never puts a service in front of a plain CRUD write (Bennett's
objection), and it never scatters multi-model logic across views and serializers
(HackSoft's objection).

```python
# app/models.py — single-model logic belongs here
class Booking(models.Model):
    ...
    @property
    def is_cancellable(self) -> bool:
        return self.status == Status.CONFIRMED and self.check_in > timezone.localdate()


class BookingQuerySet(models.QuerySet):
    def arriving_on(self, day):
        return self.filter(check_in=day, status=Status.CONFIRMED)


# app/services.py — multi-model orchestration + side effects belong here
@transaction.atomic
def booking_cancel(*, booking: Booking, actor: User, reason: str) -> Booking:
    if not booking.is_cancellable:
        raise ValidationError("Booking is not cancellable.")

    booking.status = Status.CANCELLED
    booking.full_clean()
    booking.save(update_fields=["status"])

    Refund.objects.create(booking=booking, amount=booking.deposit, reason=reason)
    transaction.on_commit(lambda: notify_guest_cancelled.delay(booking.pk))
    return booking
```

Conventions worth copying from HackSoft, independent of the debate:

- **Keyword-only arguments** (the leading `*`) so call sites are self-documenting.
- **`@transaction.atomic` on mutating services**, so persistence and consistency
  are decided at one layer rather than in every view.
- **Return ORM instances, not DTOs.** HackSoft's own reference implementation
  returns `BaseUser` from `user_create()` and a raw `QuerySet` from `user_list()`.
  No reputable Django voice argues for DTOs at app boundaries; the serializer is
  already the boundary contract. Don't build a parallel object model.

### Signals

**Don't use signals for domain logic.** They make the data flow implicit and
untraceable — which is the whole problem a boundary is supposed to solve.

Signals are fine for genuinely unrelated concerns: cache invalidation, audit
logging, search reindexing. If app A must cause an effect in app B as part of a
business rule, call a service function or enqueue a named Celery task — both are
greppable.

Signal footguns to remember regardless:

- `bulk_create()`, `bulk_update()`, `QuerySet.update()` and `QuerySet.delete()`
  **do not fire** per-instance signals.
- Signals do not fire during fixture loading in the normal way (`raw=True`), and
  handler exceptions propagate into the caller's control flow.
- `pre_save`/`post_save` fire **before** M2M relations are populated.

### Rules

- ✅ Single-model logic → model / manager / queryset.
- ✅ Multi-model or side-effect-bearing logic → `services.py`, keyword-only, atomic.
- ✅ Read logic that needs filtering/annotation → `selectors.py` returning a QuerySet.
- ❌ Business logic in views, serializers, or forms.
- ❌ Business logic in signals.
- ❌ DTOs at app boundaries — return model instances.

---

## 2. App boundaries and how to enforce them

A 15-app monolith degrades into a big ball of mud the moment imports go in every
direction. The fix is not splitting into services — it is making the import graph
directional and enforcing it in CI.

### Declare the layering

Pick a layering and write it down. A typical shape:

```
core / common          (no imports from other apps)
    ↑
domain apps            (may import core; must not import each other, or only downward)
    ↑
api / interface layer  (may import anything below)
```

### Enforce with import-linter

[import-linter](https://import-linter.readthedocs.io/) (David Seddon) validates
the graph in CI. v2.7 ships five contract types:

| Contract | Enforces |
|---|---|
| `layers` | higher layers may import lower, never the reverse |
| `forbidden` | module set A may not import module set B |
| `independence` | two apps with zero dependency in either direction |
| `protected` | a module is importable only by `allowed_importers` — this is how you make `services.py` the app's *public* API and `models.py` private |
| `acyclic_siblings` | no cycles between sibling modules |

```ini
# .importlinter
[importlinter]
root_package = myproject

[importlinter:contract:layers]
name = App layering
type = layers
layers =
    myproject.api
    myproject.billing | myproject.bookings | myproject.cleaning
    myproject.core

[importlinter:contract:public-api]
name = Cross-app access goes through services
type = forbidden
source_modules = myproject.billing
forbidden_modules = myproject.bookings.models
allow_indirect_imports = True
```

Run `lint-imports` as a required CI check.

**Adopting on a legacy codebase:** `ignore_imports` whitelists existing
violations so the contract passes today and blocks *new* ones. It is a manual
per-import list, not an automated snapshot — for hundreds of violations, start
with the `layers` contract on the two or three apps you care about most and widen
over time. `unmatched_ignore_imports_alerting = warn` stops stale ignores from
breaking the build while you clean up.

`tach` is a viable alternative (declared dependencies, public interfaces, no
cycles, via `tach.toml`) but has no Django-specific guidance and no baseline file.
Default to import-linter.

### Avoiding cross-app model imports

- Use **string references** for relations: `models.ForeignKey("bookings.Booking")`.
- Use **`settings.AUTH_USER_MODEL`**, never `from django.contrib.auth.models import User`.
- Use `django.apps.apps.get_model("bookings", "Booking")` when you genuinely need
  runtime lookup — but treat reaching for it as a smell. As Ken Whitesell puts it
  on the Django forum: if two apps' models are that entangled, ask why they are
  separate apps.

### When *not* to split the monolith

A well-layered monolith is the correct default. Splitting into separate services
converts every in-process function call into a network call with partial failure,
versioning, and distributed-transaction problems — and it does not fix a bad
import graph, it just makes it a bad network graph. Fix the boundaries in-process
first; you will usually find you no longer want to split.

---

## 3. DRF: views, serializers, validation

### Choosing a view class

DRF's hierarchy is `APIView` → `GenericAPIView` + mixins → `ViewSet` / `ModelViewSet`.

| Use | When |
|---|---|
| `ModelViewSet` | full CRUD on one model with router-generated URLs |
| `ReadOnlyModelViewSet` | list + retrieve only |
| `GenericViewSet` + explicit mixins | you want three of the five actions — the lean default |
| Generic views (`ListCreateAPIView`, …) | standard CRUD where you'd rather see the URLconf explicitly |
| `APIView` | anything non-CRUD: actions, reports, webhooks, RPC-ish endpoints |

DRF's own docs are clear that plain views + explicit URLconf are *more* readable
and controllable; ViewSets trade explicitness for DRY routing. Don't reach for
`ModelViewSet` reflexively for an endpoint that isn't CRUD.

**Gotcha:** `self.action` is **not yet set** during `get_parsers()`,
`get_authenticators()` and `get_content_negotiator()` — per-action logic in those
hooks silently misbehaves. Per-action `get_serializer_class()` / `get_permissions()`
are fine.

```python
class BookingViewSet(GenericViewSet, ListModelMixin, RetrieveModelMixin, CreateModelMixin):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Tenant scoping belongs HERE — see §10.
        return (
            Booking.objects
            .filter(property__organisation=self.request.user.organisation)
            .select_related("property", "guest")
        )

    def get_serializer_class(self):
        return BookingWriteSerializer if self.action == "create" else BookingReadSerializer

    def perform_create(self, serializer):
        # Request-implicit data belongs here, not in the serializer.
        serializer.save(created_by=self.request.user)
```

### Serializers

- **List `fields` explicitly. Never `__all__`.** With `__all__`, adding a model
  field silently exposes it through the API — a security bug waiting for the next
  migration.
- **Separate read and write serializers** once they diverge. One serializer doing
  both with a pile of `read_only`/`write_only` flags is harder to reason about
  than two.
- **Writable nested relations are not automatic** — you must write `create()` /
  `update()` by hand. Usually the better answer is a flat payload with a PK, or a
  dedicated action endpoint.
- **Object-level `validate()` on PATCH only sees submitted fields**, not full
  object state. Any cross-field rule must handle the partial case explicitly:

```python
def validate(self, attrs):
    check_in = attrs.get("check_in", getattr(self.instance, "check_in", None))
    check_out = attrs.get("check_out", getattr(self.instance, "check_out", None))
    if check_in and check_out and check_out <= check_in:
        raise serializers.ValidationError("check_out must be after check_in.")
    return attrs
```

### The validation-placement trap

**DRF does not call `Model.full_clean()` when a `ModelSerializer` saves.** This was
a deliberate 3.0 design decision (the maintainer rationale is avoiding
partially-instantiated objects with unsaved relations), and the maintainers have
said they don't intend to change it — see [DRF Discussion #7850](https://github.com/encode/django-rest-framework/discussions/7850).

The consequence is the important part: **`Model.clean()` and model field
validators are dead code on the API write path unless you wire them up.** Teams
routinely discover years-old invalid rows because a rule lived in `clean()` and
the API never called it. The discussion thread shows sustained community
disagreement with the decision, but the behaviour is what it is.

Pick one of these and apply it consistently:

1. **Validate in the service layer** (recommended if you followed §1) — the
   service calls `full_clean()` before `save()`, and the serializer only does
   shape/type validation. One place to look, works from API, admin and management
   commands alike.
2. **Call `full_clean()` in `Model.save()`** — simplest, but costs a validation
   pass on every write including bulk paths that then bypass it anyway.

Whichever you pick, translate Django's `ValidationError` into a DRF error
response with a custom `EXCEPTION_HANDLER`, or clients get a 500 instead of a 400.

### Pagination

`PageNumberPagination`, `LimitOffsetPagination`, `CursorPagination` ship with DRF.

**Paginate every list endpoint** — an unpaginated list is a production incident
scheduled for the day the table grows.

`CursorPagination` is right for large or fast-changing datasets: it avoids the
`OFFSET n` scan cost and can't skip or duplicate rows when records are inserted
mid-pagination. Its ordering field must be **unchanging, unique or near-unique,
indexed, and not a float**. `-created_at` is the usual choice; add a unique
tiebreaker if timestamps can collide.

Pagination is applied automatically only by generic views and ViewSets. In a
plain `APIView` you must invoke the paginator yourself.

### DRF vs django-ninja

**Stay on DRF.** For an existing DRF codebase there is no argument. For greenfield
in 2026 the honest answer is that no authoritative source settles it: Ninja is
async-first with Pydantic v2 schemas and automatic OpenAPI, but DRF's ecosystem
(django-filter, drf-spectacular, simplejwt, permissions) is materially more
mature, and the one source arguing for Ninja concedes exactly that. Not a reason
to migrate a working API.

---

## 4. ORM performance discipline

Almost every Django performance problem is a query-count problem.

### select_related vs prefetch_related

| | `select_related` | `prefetch_related` |
|---|---|---|
| Mechanism | SQL JOIN, one query | separate query per relation, joined in Python |
| Works for | forward FK, OneToOne | M2M, reverse FK, GenericRelation — and everything above |
| Cost | row duplication across the join | one extra query |

When unsure, **`prefetch_related` is the safe default** (Adam Johnson's advice) —
it can't blow up row counts.

Combine them with a `Prefetch` object when the prefetched rows themselves have
relations:

```python
bookings = (
    Booking.objects
    .select_related("property")                      # forward FK → JOIN
    .prefetch_related(
        Prefetch(
            "guests",
            queryset=Guest.objects.select_related("nationality"),  # avoid N+1 inside the prefetch
        )
    )
)
```

### The traps

- **Callable attributes re-query every time.** `booking.guests.all()` issues a
  query on each call. Templates call callables silently, so a `{% for g in booking.guests.all %}`
  inside a loop over bookings is an N+1 you cannot see in the Python source.
- **`only()` / `defer()` invert into N+1.** Touching a deferred field triggers a
  per-instance query. Use them only when you've measured that column width is the
  problem.
- **QuerySets cache per instance, not globally.** Two separately-constructed
  QuerySets each hit the DB. Reuse the evaluated one rather than calling
  `.exists()` then iterating.
- **Slicing an unevaluated QuerySet (`qs[5]`) queries without populating the cache.**
- **`repr(qs)` doesn't populate the cache** — it materialises only a slice, so
  printing a queryset in a debugger then iterating costs two queries.
- **`bulk_create` / `bulk_update` / `QuerySet.update()` / `QuerySet.delete()`
  bypass `save()`, `delete()` and their signals.** Fast and correct, as long as
  nothing important lives in `save()`.

### Reaching for the right tool

```python
Booking.objects.values_list("id", flat=True)          # ids only — no model instantiation
Booking.objects.aggregate(total=Sum("amount"))        # aggregate in SQL, never in Python
Booking.objects.iterator(chunk_size=2000)             # large scans, bounded memory
```

Aggregate in the database. Summing a queryset in a Python loop is the single most
common avoidable performance bug in a Django codebase.

### Tooling

- **django-debug-toolbar** SQL panel — first stop in development.
- **django-silk** — request/query profiling that works on a deployed environment.
- **`QuerySet.explain()`** — note that on **MySQL it accepts only a `format`
  option** (`TRADITIONAL` or `JSON`); the rich `analyze`/`buffers`/`timing`
  options are PostgreSQL-only.
- **`nplusone`** is effectively unmaintained (no Django 4/5-era releases, Python 2
  references in its CI config). Don't add it to a new project.
- **`django-auto-prefetch`** auto-prefetches on attribute access — a reasonable
  safety net for a legacy codebase, not a substitute for explicit prefetching.

Measure before and after. A query-count assertion in a test
(`assertNumQueries`) is the only thing that stops an N+1 from coming back.

---

## 5. Celery in production

### Idempotency is the precondition, not an optimisation

Celery delivery is **at-least-once**. Any task can run twice: on retry, on
redelivery after a visibility timeout, on worker restart. Write every task so a
second execution is harmless — check state before acting, use
`get_or_create`/`update_or_create`, key external calls on an idempotency token.

If a task cannot be made idempotent, that is a design problem to solve before
adding retries, not after.

### Acknowledgement and worker loss

```python
@shared_task(
    bind=True,
    acks_late=True,
    autoretry_for=(RequestException,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def sync_reservation(self, reservation_id): ...
```

- **`acks_late=True`** acks *after* execution instead of on receipt, so a worker
  crash mid-task redelivers rather than loses the task. Requires idempotency.
- The at-least-once guarantee is **conditional**: an `acks_late` worker still acks
  when the child process dies via `sys.exit()`, a signal, or a segfault/OOM kill —
  deliberately, to avoid an infinite redelivery loop on a task that reliably kills
  its worker. Don't promise "never lost" to stakeholders.
- **`task_reject_on_worker_lost=True`** re-queues on mid-execution worker death.
  Pair with `acks_late`, accepting duplicate risk.
- **`task_retry_on_worker_lost=True`** — **avoid.** Outside the prefork pool Celery
  can't distinguish an OOM kill from normal termination, producing infinite retry
  loops.
- **Always bound `max_retries`.** `None` means forever.
- Retry on **specific** exceptions. `autoretry_for=(Exception,)` retries your
  `ValidationError` and your `TypeError` five times before failing.

### The Redis visibility-timeout trap

With a Redis broker, a task that has not been acked within `visibility_timeout`
(default **3600s**) is redelivered to another worker. Combined with `acks_late`,
any task running longer than an hour is redelivered *while still running* — and
can re-schedule itself indefinitely.

```python
broker_transport_options = {"visibility_timeout": 7200}
result_backend_transport_options = {"visibility_timeout": 7200}
```

Set it consistently in **both** places and above your longest task runtime.

The same trap applies to `countdown`/`eta`: a task scheduled further out than the
visibility timeout gets redelivered repeatedly. **Do not schedule far-future work
with `eta`.** Store a due-date on a model and have a periodic beat task pick it
up — ETA tasks are held in worker memory and are lost on restart anyway.

### Dispatch after commit, always

```python
# Wrong: the worker can pick this up before the transaction commits,
# and read a row that doesn't exist yet.
booking.save()
send_confirmation.delay(booking.pk)

# Right:
booking.save()
transaction.on_commit(lambda: send_confirmation.delay(booking.pk))

# Right, Celery 5.4+ shorthand:
send_confirmation.delay_on_commit(booking.pk)
```

This race is real and intermittent, which makes it expensive to debug. Make it a
review rule: **a `.delay()` inside an atomic block is a bug**.

### Queues, results, Redis config

- **Route by workload, not by app**: separate queues for beat-scheduled work,
  latency-sensitive work, and long-running jobs, so a batch job can't starve a
  user-facing task. Configure routing in `task_routes`, not by hard-coding
  `queue=` at call sites.
- **`ignore_result=True`** for fire-and-forget tasks. Otherwise every task writes
  a result nobody reads.
- `result_expires` only takes effect if **beat runs `backend_cleanup`**. Without
  beat, results accumulate forever.
- **Redis `maxmemory-policy` must be `noeviction`** (or `allkeys-lru` with care).
  Under other policies Redis evicts Kombu binding keys and Celery raises
  `InconsistencyError`.
- **Keep tasks thin.** A task should deserialize arguments and call a service
  function. That makes the logic testable without Celery at all — which is the
  point, since eager mode is not a substitute for a worker (see §13).

### Anti-entropy

At-least-once delivery plus retries plus visibility timeouts means some work will
still be missed. A periodic "sweeper" task that rescans for records in a stale
state and re-enqueues them is the practical complement — cheap to write,
repeatedly the thing that saves you.

---

## 6. Channels and websockets

### Sync consumers by default

Write `SyncConsumer`/`JsonWebsocketConsumer` unless you have a specific reason not
to. An `AsyncConsumer` that calls any slow synchronous code **blocks the entire
event loop** for every connection on that process — a much worse failure than a
blocked thread. Go async only when the consumer is async all the way down.

### Database access

The ORM is synchronous. From an async consumer:

```python
from channels.db import database_sync_to_async

@database_sync_to_async
def get_booking(pk):
    return Booking.objects.select_related("property").get(pk=pk)
```

`database_sync_to_async` wraps `sync_to_async` *and* cleans up the connection.
Django's native async ORM methods (`aget`, `acreate`, `afirst`, `async for`,
Django 5.0+) are an alternative — but **transactions still do not work in async
context**, so any multi-statement write must go through a sync function.

**Connection leak to know about:** Channels calls `close_old_connections()` on
connect, disconnect and receive — **but not on send**. A long-lived consumer that
mostly sends will accumulate stale connections. Call `aclose_old_connections()`
periodically in such consumers.

Never set `DJANGO_ALLOW_ASYNC_UNSAFE` in production — it disables the
`SynchronousOnlyOperation` guard that is telling you about a real bug.

### Routing

```python
# asgi.py
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
```

Routing happens at connection/scope level only; URL kwargs arrive at
`scope["url_route"]["kwargs"]`. `ASGI_APPLICATION` points at this module.

### Celery vs Channels workers

Channels has its own "worker and background tasks" concept. In a project already
running Celery, **use Celery for background work** and keep Channels to the
websocket transport. Two task systems is a maintenance tax with no payoff.

---

## 7. Async Django: when it actually helps

Async views are a targeted tool, not a throughput upgrade.

**Worth it for:** long-lived connections (websockets, SSE, long-polling), views
that fan out to several slow external APIs concurrently, very high connection
counts with mostly-idle sockets.

**Not worth it for:** ordinary CRUD and DB-bound views. The ORM is sync; an async
view that awaits `sync_to_async` ORM calls is strictly slower than the sync
equivalent.

Deployment gotchas:

- **One synchronous middleware anywhere in the stack forces async views into
  thread-per-request**, eliminating most of the benefit. Audit `MIDDLEWARE` before
  concluding async isn't working.
- Each sync/async context switch costs roughly a millisecond. Mixed stacks pay it
  repeatedly.
- Supported ASGI servers are **Daphne, Hypercorn and Uvicorn**. Gunicorn can
  supervise Uvicorn workers; uWSGI is not an ASGI server.
- **Transactions do not work in async context** as of Django 5.x.

Default to WSGI unless you are running Channels or have a measured async win.

---

## 8. Migrations and schema safety on MySQL

MySQL 8's constraints drive this whole section:

- **No transactional DDL.** A migration that fails halfway cannot roll back — you
  unpick it by hand. `atomic = False` has no effect on DDL here; it exists to stop
  a long data migration holding one enormous transaction.
- **Tighter combined index-size limits than PostgreSQL** — a composite/covering
  index that is fine on Postgres may be rejected on MySQL 8.
- **Adding a column with a default can rewrite the whole table**, even when the
  column is nullable.

### The rules

**Small, reversible, one concern per migration.** On a database that can't roll
back DDL, migration size is a risk multiplier.

**Separate schema changes from data changes.** Never put a `RunPython` backfill in
the same migration as the `AddField` it depends on.

**Use `Field.db_default` (Django 5.0+)** for additive columns — it persists a real
database-level default and supersedes the old MySQL strict-mode workaround
tracked in ticket #29266. Guides recommending `django-add-default-value` or the
old nullable-then-backfill dance purely for defaults are now stale.

**Adding a NOT NULL column to a populated table** is still three deploys:

1. Add the column nullable (or with `db_default`).
2. Backfill in a separate data migration, batched.
3. Add the `NOT NULL` constraint.

**Data migrations must use historical models:**

```python
def backfill(apps, schema_editor):
    Booking = apps.get_model("bookings", "Booking")   # NOT a direct import
    db = schema_editor.connection.alias
    qs = Booking.objects.using(db).filter(reference="")
    for chunk in chunked(qs.iterator(chunk_size=1000), 1000):
        Booking.objects.using(db).bulk_update(chunk, ["reference"])

class Migration(migrations.Migration):
    atomic = False        # don't hold one transaction across a long backfill
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
```

Historical models have **no custom `save()`, no custom managers' business logic,
no instance methods**. A direct import works today and breaks the day someone
replays migrations from zero.

**Squashing is a two-release process:** squash while keeping the old files →
release → wait until every environment is past the squash point → delete the old
files → release again.

### CI gates

- `python manage.py makemigrations --check --dry-run` — fails when a model change
  has no migration. This is **not** the same as testing that migrations apply.
- **Run `migrate` from an empty database in CI.** That is what catches a
  `RunPython` that imports a model directly, or a migration that depends on data
  only production has.
- **[django-linear-migrations](https://adamj.eu/tech/2020/12/10/introducing-django-linear-migrations/)**
  (Adam Johnson) maintains a per-app `max_migration.txt` so two branches adding
  migrations produce an ordinary **git merge conflict at development time**
  instead of a silent duplicate-leaf-node that `makemigrations --merge` discovers
  after merge. It adopts cleanly on a legacy project — it only enforces linearity
  forward from the current leaf.

**Adopting migrations on tables that already exist:** `makemigrations` then
`migrate --fake-initial`, which is only safe if the models haven't changed since
the tables were created and nobody hand-edited the schema.

### Large tables: know which ALTERs are cheap

Before assuming you need a tool, check whether InnoDB can do it natively:

| Algorithm | Cost | Notes |
|---|---|---|
| `INSTANT` | metadata only | add column (8.0.12+), drop column (8.0.29+). **Not** available on `ROW_FORMAT=COMPRESSED`, FULLTEXT-indexed or temp tables; capped at 64 row versions before a rebuild is forced |
| `INPLACE` | rebuilds without a temp table | DML usually allowed |
| `COPY` | full copy | **blocks DML** — this is the one that takes the site down |

Django doesn't let you pick the algorithm directly; for a large table, run the DDL
yourself and mark the migration as already-applied
(`migrations.SeparateDatabaseAndState`), or use an external tool.

### External online-schema-change tools

Django provides no online-DDL strategy, and the well-known zero-downtime packages
(`django-pg-zero-downtime-migrations`, and friends) are **PostgreSQL-oriented with
no MySQL equivalent**. On MySQL the options are:

| | **pt-online-schema-change** (Percona) | **gh-ost** (GitHub) |
|---|---|---|
| Mechanism | triggers + chunked copy + atomic rename | triggerless — tails the binlog (requires RBR, MySQL 5.7+) |
| Foreign keys | supported via `--alter-foreign-keys-method` | **not supported** |
| Resumable | yes (`--resume`) | no — if it dies, start over |
| Throttling | pauses/aborts on `Threads_running` (25/50 defaults) or replica lag | true pause/resume, can test against a replica |
| Managed MySQL (Cloud SQL, RDS) | trigger overhead on the primary | generally friendlier |

**Rule of thumb:** foreign keys → pt-osc. No foreign keys and a managed instance →
gh-ost. Neither integrates with Django migrations, so the workflow is: run the tool
manually, then fake the migration.

Preflight checklist for any large-table change: free disk ≥ table size, no
long-running transactions holding metadata locks, replica lag healthy, no existing
triggers that would collide with pt-osc.

**Metadata locks are the usual surprise** — a single long-running `SELECT` or an
idle-in-transaction connection blocks the `ALTER`, and then everything queues
behind the `ALTER`. Check `performance_schema.metadata_locks` before you start.

---

## 9. Settings, configuration, secrets

### One settings module, environment-driven

The `settings/base.py` + `settings/dev.py` + `settings/prod.py` split is the common
pattern and the common source of "works on my machine": the environments diverge in
ways nobody reviews, and the module that runs in production is the one least
exercised. Prefer **a single `settings.py` whose values come from the
environment**, with the differences between environments expressed as
*environment variables*, not as *different code paths*.

```python
# settings.py
import environ

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(BASE_DIR / ".env")     # local dev only; absent in prod

SECRET_KEY   = env("SECRET_KEY")             # no default → fails fast if unset
DEBUG        = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
DATABASES    = {"default": env.db("DATABASE_URL")}
CACHES       = {"default": env.cache("REDIS_URL")}
```

`django-environ` gives you the URL parsers (`env.db()`, `env.cache()`) that turn a
single connection string into the nested dict Django wants. `pydantic-settings` is
the alternative if you want typed validation of the whole config object; it costs
you the URL parsers.

The rules that matter more than the library choice:

- **No default for a secret.** `env("SECRET_KEY")` with no fallback means a
  misconfigured deploy crashes at import time instead of running with a known-public
  key. A default of `"dev-insecure"` will reach production eventually.
- **Where a `settings/` package is genuinely justified** — test settings that must
  differ structurally (a different `DATABASES` for xdist, `MIGRATION_MODULES`
  overrides) — keep the override module tiny and have it `from .settings import *`.
  Everything else stays environment-driven.
- **`DEBUG = True` must be impossible in production.** It leaks settings and SQL in
  tracebacks and disables `ALLOWED_HOSTS` enforcement.
- **Fail loudly on unparseable config.** A `try/except` around config reading that
  falls back to a default converts a deploy-time error into a runtime mystery.

### Secrets

Environment variables are the interface; they are not the store. In order of
preference:

1. **The platform's secret manager** (GCP Secret Manager, AWS Secrets Manager,
   Vault) injected into the process environment by the deployment layer. The app
   reads `os.environ` and knows nothing about the backend.
2. **A mounted secrets file** the app reads at startup.
3. **`.env` files — local development only.** Gitignored, never committed, never
   shipped in an image.

Never bake secrets into a Docker image (they persist in layer history), never pass
them as build args, and never log the settings object.

Rotation matters more than storage: assume every credential will leak eventually and
make sure you can rotate `SECRET_KEY` (which invalidates sessions and password-reset
tokens — plan for that), database passwords and API keys without a code change.

### The deploy gate

`python manage.py check --deploy --fail-level WARNING` in CI, against the production
settings. It catches `DEBUG=True`, a missing `SECURE_HSTS_SECONDS`,
`SESSION_COOKIE_SECURE = False`, weak `ALLOWED_HOSTS`, and a handful of other
foot-guns. It's a five-minute integration that pays for itself the first time.

---

## 10. Security

### Authorization: the queryset is the permission boundary

DRF gives you two hooks and they cover different things. Confusing them is the most
common authorization bug in DRF codebases:

| | `has_permission` | `has_object_permission` |
|---|---|---|
| Runs on | every request | a single object |
| List endpoints | ✅ | ❌ **never called** |
| Detail endpoints | ✅ | ✅ — but only via `get_object()` |

**`has_object_permission` is never invoked for list actions.** There is no object
yet. If your authorization lives only there, `GET /api/bookings/` returns every
booking in the database to every authenticated user, and the detail endpoint looks
correct in review.

So: **scope in `get_queryset()`, and treat `has_object_permission` as
defence-in-depth**, not as the control.

```python
def get_queryset(self):
    return Booking.objects.filter(property__owner=self.request.user)
```

This also gives you the right status code for free — an out-of-scope ID becomes a
404 rather than a 403, which avoids confirming that the object exists.

Two follow-on traps:

- **`check_object_permissions` only runs if you go through `get_object()`.** Any
  custom action that fetches with `Model.objects.get(pk=...)` directly skips
  permission checks entirely.
- **A `queryset` class attribute plus a custom `get_queryset()`** — DRF uses
  `get_queryset()`, but router basename inference and some third-party filters read
  the attribute. Keep them consistent or set `basename` explicitly.

### Throttling: understand what it is and isn't

DRF throttling is a **cache-counter, not a rate limiter**. Two facts govern how you
use it:

1. **It is not atomic.** Read-modify-write against the cache races under
   concurrency, so the effective limit under load is higher than configured.
2. **It is only as shared as your cache.** With `LocMemCache`, each Gunicorn worker
   keeps its own counter — 8 workers means 8× the configured limit. Throttling
   requires a shared Redis or Memcached backend to mean anything.

Therefore: DRF throttling is for **shaping legitimate client behaviour** (protecting
an expensive report endpoint, discouraging polling). **DoS protection belongs at the
edge** — Cloud Armor, a WAF, nginx `limit_req`. Never present DRF throttling as your
abuse defence.

Configure per-scope rather than globally:

```python
class ReportViewSet(ViewSet):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "reports"

# settings.py
REST_FRAMEWORK = {
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/hour", "reports": "10/hour"},
}
```

`AnonRateThrottle` keys on IP, so it is defeated by rotation and mis-fires behind a
proxy unless `X-Forwarded-For` handling is correct — an incorrectly trusted
forwarding header lets a client set their own throttle key. `UserRateThrottle` keys
on the authenticated user and is the more meaningful of the two.

**Decide what happens when the cache is down.** DRF's throttle will raise, turning a
Redis outage into a total API outage. If throttling is a convenience rather than a
control, catch and allow.

### Keep up with security releases

Django ships security releases on a regular cadence, and 2025–2026 saw a run of them
covering SQL-injection vectors (notably through `FilteredRelation` and column
aliases reachable via `annotate()` / `order_by()`), DoS via pathological input to
several parsers and validators, and log-injection issues.

The `order_by` class matters directly to DRF: **`OrderingFilter` passes
client-supplied strings into `order_by()`.** Always constrain it —
`ordering_fields = ["created_at", "name"]`, never `ordering_fields = "__all__"` —
and never interpolate request data into `extra()`, `RawSQL`, or `.raw()`.

Operationally:

- Pin to a **LTS** release and subscribe to `django-announce`.
- Run `pip-audit` (or `uv pip audit`) in CI and fail the build on a known-vulnerable
  dependency.
- Treat a Django patch release as a same-week deploy, not a quarterly chore.

⚠️ *Verify specific CVE identifiers and their fixed-version ranges against
[the Django security archive](https://docs.djangoproject.com/en/dev/releases/security/)
before acting — the mapping between individual CVEs and patch versions was not
independently confirmed for this document.*

### The unglamorous baseline

Most Django compromises aren't framework CVEs:

- `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`,
  `SECURE_HSTS_SECONDS` — all covered by `check --deploy` (§9).
- **CSRF applies to session-authenticated DRF endpoints.** `SessionAuthentication`
  enforces it; token/JWT auth does not need it. A SPA on the same origin using
  session cookies must send the token.
- **CORS is not authorization.** `CORS_ALLOW_ALL_ORIGINS = True` with
  `CORS_ALLOW_CREDENTIALS = True` is the combination to never ship.
- **File uploads**: validate content type server-side, never trust the filename,
  and serve user uploads from a separate origin so a stored HTML file can't run in
  your domain's context.

---

## 11. Caching

### Backend: built-in `RedisCache` first

Django has shipped a first-party `django.core.cache.backends.redis.RedisCache`
since 4.0. Start there. Reach for **django-redis** only when you need something it
provides — richer client configuration, `get_or_set` semantics you rely on, master/
replica routing, pattern-based `delete_pattern()`, or the raw client via
`get_redis_connection()`.

⚠️ *The exact feature delta between the built-in backend and django-redis (connection-pool
customisation, replica support) was not verified for this document — check the
current Django docs before assuming parity in either direction.*

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL"),
        "KEY_PREFIX": "dolce",     # namespace — lets you share one Redis
        "TIMEOUT": 300,
    }
}
```

**Never use `LocMemCache` for anything that must be consistent across processes.**
It is per-process: each Gunicorn worker has its own copy, so invalidation in one
worker doesn't reach the others, and throttle counters (§10) multiply by worker
count. It's fine as the *test* backend and nowhere else.

**Give sessions, cache and Celery separate Redis databases or key prefixes.** A
`cache.clear()` that also drops every session is a bad afternoon.

### Timeout semantics are a foot-gun

| Value | Meaning |
|---|---|
| `timeout=None` | **cache forever** |
| `timeout=0` | **don't cache at all** (expires immediately) |
| omitted | use the backend's `TIMEOUT` setting |

`None` and `0` read as "no timeout" to most people and mean opposite things. Be
explicit.

### Invalidation: prefer expiry and key versioning over deletion

Chasing down every write path that should invalidate a key is how caches go stale.
Two more durable approaches:

1. **Short TTLs.** If 60 seconds of staleness is acceptable, a 60-second TTL removes
   the entire invalidation problem. Most read-heavy endpoints tolerate this.
2. **Version the key, don't delete it.** Include a mutable component in the key —
   `f"property:{pk}:v{obj.updated_at.timestamp()}"` — so a write produces a new key
   and the old one ages out on its own. No delete call to forget.

If you do delete explicitly, do it **in `transaction.on_commit()`**, for the same
reason Celery dispatch does (§5): invalidating before commit lets a concurrent read
repopulate the cache with the pre-commit value.

### Cache stampede

When a hot key expires, every concurrent request misses simultaneously and all of
them run the expensive query. `cache.get_or_set()` does **not** prevent this — it is
not atomic across processes.

Mitigations, in increasing order of effort:

- **Jitter the TTL** (`300 + random.randint(0, 60)`) so keys spread out rather than
  expiring in lockstep. Solves the correlated case cheaply.
- **A lock around recomputation** (`cache.add(lock_key, ...)` as a mutex; `add` is
  atomic where `set` isn't) — one worker recomputes, the others serve stale or wait.
- **Recompute ahead of expiry** from a Celery beat task for genuinely expensive,
  genuinely hot values.

### What to cache

Cache **computed results**, not ORM objects. Pickled model instances go stale in
ways that are hard to reason about and break across model changes. Cache the
serialized payload, the aggregate, the rendered fragment.

**Per-site and per-view caching (`UpdateCacheMiddleware`, `@cache_page`) are almost
never right for an authenticated API.** They key on the URL, so unless every varying
input is in `Vary:`, you will eventually serve one user's data to another. For DRF,
cache inside the view — around the expensive call — where you control the key and
it includes the user.

Before adding a cache, confirm the query is actually the problem. A cache layered
over an N+1 (§4) hides the bug and doubles the failure modes.

---

## 12. Logging and observability

### Structured logs, correlated by request

Plain-text logs stop being useful the moment you have more than one worker. Use
**structlog** with **django-structlog**, which does the part you'd otherwise write
badly yourself: it binds a `request_id` to a context-local at the start of each
request and emits it on every log line produced downstream — including,
crucially, **inside Celery tasks dispatched from that request**. That one field is
what turns "an error happened" into "here is the entire causal chain".

```python
MIDDLEWARE = [
    "django_structlog.middlewares.RequestMiddleware",   # early in the list
    ...
]
```

It also emits `request_started` / `request_finished` / `request_failed` events with
timing, and Django/Celery signals you can subscribe to for audit purposes.

Write logs as events with fields, never as interpolated prose:

```python
logger.info("booking.confirmed", booking_id=booking.pk, amount=str(total))
# not: logger.info(f"Confirmed booking {booking.pk} for {total}")
```

The first is queryable; the second requires a regex forever.

### Configuration rules

- **JSON to stdout in production, human-readable in dev.** The container runtime
  collects stdout. Do not write log files inside a container, and do not configure
  `RotatingFileHandler` there — you'll get interleaved rotation from multiple
  workers and lose lines.
- **`"disable_existing_loggers": True`** in a `LOGGING` dictConfig silently kills
  library loggers, including Django's own. Leave it `False` unless you know exactly
  what you're switching off.
- **`django.db.backends` at DEBUG logs every query.** Invaluable locally, ruinous in
  production. Guard it on `DEBUG`.
- **Never log secrets, tokens, session keys or full request bodies.** Add a
  structlog processor that redacts known-sensitive keys, so redaction is a property
  of the pipeline rather than of each call site.

### Errors, traces, metrics

- **Sentry** for exceptions. Set `send_default_pii = False` unless you've decided
  otherwise deliberately, configure `traces_sample_rate` well below 1.0 in
  production, and set the `release` so regressions are attributable to a deploy.
- **OpenTelemetry** if you need distributed traces across engine → Celery →
  external services. Auto-instrumentation for Django, DB drivers and requests gets
  you most of the way; the manual work is propagating context into Celery.
- **Health endpoints**: a liveness check that only proves the process is up, and a
  readiness check that proves DB and cache are reachable. Conflating them means a
  Redis blip restarts your pods.

### Development-time profiling

`django-debug-toolbar` for pages, **`django-silk`** for API endpoints (it records
SQL per request and works where the toolbar's HTML injection can't). Both are
development-only — mounting Silk in production exposes request bodies.

For the specific problem of "which endpoint is doing N+1", `nplusone` in CI (§4)
catches it earlier and more cheaply than any observability tool catches it later.

---

## 13. Testing

### Runner: pytest as runner, Django's TestCase as base

The Django-core-adjacent voices (Adam Johnson, Claude Paroz, James Bennett) lean
toward keeping Django's `TestCase`; pytest advocates want fixtures and
parametrisation. Adam Johnson's hybrid is the reconciling position and the one to
adopt:

**Run tests with pytest. Subclass Django's `TestCase`. Write plain `assert`.**

That keeps `setUpTestData`, the `databases` attribute and `installed_apps`
handling — which pytest-django does not natively replicate — while getting
pytest's runner, parametrisation and output.

pytest-django specifics:

- It **replaces** `manage.py test` as the entry point rather than wrapping it.
- **DB access is blocked by default** since 3.0 — opt in with
  `@pytest.mark.django_db` or the `db` fixture. This is a feature: it makes
  accidental DB dependence visible.
- **`--reuse-db` does not detect schema changes.** Put `--reuse-db` in
  `pytest.ini` and run `pytest --create-db` after changing models. Forgetting this
  produces baffling failures.
- **`--nomigrations`** speeds up DB setup but directly contradicts the
  "migrate-from-zero must always work" gate. Keep a separate CI job that runs
  migrations for real.
- **xdist** provisions one database per worker automatically (`test_foo_gw0`,
  `_gw1`, …). Never let parallel workers share one MySQL database.

### Test data: factories, not fixture blobs

Use **factory_boy**. Avoid `dumpdata`/`loaddata` JSON blobs:

- **`Model.save()` is never called during fixture load**, so any logic in `save()`
  is silently bypassed — the test exercises a state production can't produce.
- `loaddata` is destructive and non-idempotent; PK collisions raise `IntegrityError`.
- Fixtures rot: they must be updated for every model change, whether or not the
  test cares about the changed field.

Django's own docs recommend **data migrations, not fixtures, for initial data**.

```python
class BookingFactory(DjangoModelFactory):
    class Meta:
        model = "bookings.Booking"       # string ref dodges circular imports
    property = factory.SubFactory(PropertyFactory)
    check_in = factory.Faker("future_date")
```

Use `factory.random.reseed_random()` for reproducibility and `mute_signals()` when
a handler gets in the way.

### Time, money, timezones

- **Freeze time with `time-machine`, not freezegun.** freezegun does a
  find-and-replace across every imported module, so its cost scales with module
  count (~13ms on a 1,464-module Django project); time-machine patches once at the
  C layer (~15µs). On a large suite this is the difference between seconds and
  minutes. freezegun remains fine for small projects and is CPython-agnostic.
- **Run money tests against MySQL, not SQLite.** SQLite stores `Decimal` as an
  8-byte float and "can't do correctly-rounded decimal floating point arithmetic"
  — rounding bugs vanish under SQLite and reappear in production.
- **Promote naive-datetime warnings to errors** so timezone bugs fail the suite:

```python
warnings.filterwarnings("error", r"DateTimeField .* received a naive datetime")
```

### Celery and Channels

- **`task_always_eager` is not a substitute for a worker.** The Celery docs say it
  is "by definition not suitable for unit tests" — it emulates, and the emulation
  diverges. Pair it with `task_store_eager_result = True` if you use it at all,
  and prefer testing the **service function** the task calls. Test the task itself
  only for its Celery-specific behaviour (routing, retry policy).
- **Channels:** always call `WebsocketCommunicator.disconnect()` before the test
  ends or you get `RuntimeWarning`s. Wrap consumers in a `URLRouter` rather than
  instantiating directly when they expect URL kwargs.
  `ChannelsLiveServerTestCase` **cannot use in-memory SQLite** — it needs a
  file-based test database.

### External HTTP

Never let the test suite make a real outbound request. It makes tests slow, flaky,
dependent on someone else's uptime, and occasionally expensive.

| Tool | Model | Use when |
|---|---|---|
| **responses** / **respx** | you declare the expected request and the canned response | the interaction is simple and you want the contract visible in the test |
| **vcrpy** (`pytest-recording`) | records real traffic once to a cassette, replays after | the API is complex enough that hand-writing responses is unrealistic |

Prefer **responses** (for `requests`) or **respx** (for `httpx`) as the default: an
explicit stub documents what your code sends, and a test that breaks when you change
the outbound call is doing its job.

Use **vcrpy** when the payloads are large or the flow is multi-step, but treat
cassettes as a liability:

- **Scrub credentials before the cassette is written** (`filter_headers`,
  `filter_query_parameters`). Cassettes are committed; a recorded `Authorization`
  header is a leaked token. Configure this *before* the first recording, not after.
- **Re-record on a schedule.** A cassette is a snapshot of an API that will change
  without telling you; a green suite against a stale cassette is a false negative.
- Set `record_mode="none"` in CI so a cache miss fails loudly rather than silently
  reaching the network.

Whichever you use, **block the network at the suite level** so an un-stubbed call is
an error rather than a slow success — `pytest-socket`'s `--disable-socket
--allow-unix-socket` is the blunt, effective version.

For your *own* provider integrations, wrap the third party behind a thin adapter and
stub the adapter in most tests, keeping HTTP-level stubs for the adapter's own tests.
That way a provider change touches one module, not fifty test files.

### Conventions

- **Assert query counts** on list endpoints (`assertNumQueries`) — the only
  durable defence against N+1 regressions.
- **Test behaviour through the boundary you documented** — services and API
  endpoints — not private helpers. Tests that mirror the implementation break on
  every refactor and catch nothing.
- **Don't test the framework.** No tests for "does `ForeignKey` cascade", "does
  DRF return 405 on a bad verb", "does `save()` write a row".
- **Coverage is a change-detection canary, not a quality bar** (Bennett). A
  coverage percentage target produces tests written to touch lines. Use coverage
  to notice untested *new* code.

### The CI suite

Run these as separate, independently-failing jobs — a single "tests" job that
bundles them hides which guarantee broke:

| Job | What it protects |
|---|---|
| `pytest --reuse-db -n auto` | the suite itself, against **MySQL**, never SQLite |
| `pytest` with migrations applied from zero | that a fresh deploy works (§8) |
| `makemigrations --check --dry-run` | that no model change shipped without a migration |
| `check --deploy --fail-level WARNING` | production settings (§9) |
| `lint-imports` | app-boundary layering (§2) |
| `pip-audit` | known-vulnerable dependencies (§10) |

**Match the CI database to production** — same MySQL major version, same collation,
same `sql_mode`. A suite green on SQLite tells you nothing about `Decimal` rounding,
case sensitivity of string comparison, or lock behaviour.

**Coverage as a ratchet, not a target.** Configure the check to fail when coverage
*drops*, not when it sits below a round number. `diff-cover` against the base branch
is the sharper version of this: it asks "is the code you just wrote tested", which
is the question you actually care about. A global percentage target reliably produces
tests written to touch lines.

Keep the whole suite under a few minutes. Past that, developers stop running it
locally, and CI becomes the only place tests run — which is exactly when the
feedback loop is too slow to prevent the bug.

---

## 14. The API contract seam

Rules for the boundary between this backend and a JavaScript frontend. The
frontend-side counterpart is §"The API contract seam" in
[react-nextjs-best-practices.md](./react-nextjs-best-practices.md).

**The backend owns authorization. Always.** A frontend check is a UX affordance —
it hides a button. It is not a security control, because the API is reachable
without the frontend. Every endpoint re-checks permissions independently of what
the UI did.

**Scope in `get_queryset()`, not in the serializer or the view body.** For a
multi-tenant API this is the single most important line of code in the view:
filtering the queryset by the requesting user's organisation makes
object-not-found and object-not-permitted indistinguishable, which is what you
want. A `Model.objects.get(pk=...)` in a view body is an IDOR waiting to happen.

**Version the contract, don't break it silently.** Adding a field is safe;
removing or retyping one is not. If the frontend deploys separately from the
backend — and it does — then for a window both versions are live simultaneously.

**Errors need a stable shape.** Pick one envelope and make every error path use
it, including the ones DRF generates and the ones your service layer raises:

```json
{"detail": "Human readable message", "code": "booking_not_cancellable", "fields": {"check_out": ["Must be after check_in."]}}
```

A frontend cannot branch on prose. Give it a `code`.

**Paginate everything, and make the shape uniform** so the client writes one
pagination handler, not one per endpoint.

**Dates go over the wire as ISO 8601 with an offset.** Money goes as a string, not
a float — JSON numbers are IEEE doubles and will lose cents.

---

## 15. Review checklist

Architecture
- [ ] New business logic is on a model/manager (single-model) or in a service (multi-model/side-effecting) — not in a view, serializer, or signal
- [ ] Mutating service is `@transaction.atomic` with keyword-only args
- [ ] No new cross-app import that violates the layering; `lint-imports` passes

API
- [ ] Serializer lists `fields` explicitly — no `__all__`
- [ ] `get_queryset()` scopes by tenant/owner; no `objects.get(pk=...)` from request data
- [ ] List endpoint is paginated
- [ ] Model-level validation is actually invoked on the write path
- [ ] Errors use the standard envelope with a stable `code`

ORM
- [ ] `select_related`/`prefetch_related` on every list endpoint
- [ ] `assertNumQueries` test covering the endpoint
- [ ] Aggregation happens in SQL, not a Python loop

Celery
- [ ] Task is idempotent
- [ ] `max_retries` is bounded; `autoretry_for` names specific exceptions
- [ ] Dispatch is `delay_on_commit()` / inside `transaction.on_commit()`
- [ ] Long tasks are under `visibility_timeout`; no far-future `eta`

Migrations
- [ ] Schema and data changes are in separate migrations
- [ ] `RunPython` uses `apps.get_model()` and the `schema_editor` DB alias
- [ ] Backfill is batched with `atomic = False`
- [ ] `migrate` from an empty database passes in CI
- [ ] Large-table `ALTER` has a checked algorithm (INSTANT/INPLACE) or an osc plan

Config & security
- [ ] No new secret has a default value in settings
- [ ] `check --deploy` passes at WARNING
- [ ] Authorization is enforced in `get_queryset()`, not only `has_object_permission`
- [ ] `OrderingFilter`/`filterset_fields` are an explicit allowlist, never `__all__`
- [ ] No request data reaches `raw()`, `extra()` or `RawSQL`

Caching & logging
- [ ] Cache backend is shared across processes (not `LocMemCache`)
- [ ] Cache invalidation is inside `transaction.on_commit()`, or the key is versioned
- [ ] New log lines are structured events with fields, and log no secrets

Testing
- [ ] `assertNumQueries` covers any new list endpoint
- [ ] No test makes a real outbound HTTP request
- [ ] New code is covered — the diff, not the global percentage

---

## References

**Architecture**
- [HackSoft Django Styleguide](https://github.com/HackSoftware/Django-Styleguide) — services/selectors
- [James Bennett, "Against service layers in Django"](https://www.b-list.org/weblog/2020/mar/16/no-service/) — the fat-models counterargument
- [Django forum: structuring large projects](https://forum.djangoproject.com/t/structuring-large-complex-django-projects-and-using-a-services-layer-in-django-projects/1487) — the unresolved debate, multiple named voices
- [cosmicpython, Django appendix](https://www.cosmicpython.com/book/appendix_django.html) — the Data Mapper / DDD position
- [import-linter](https://import-linter.readthedocs.io/) — contract types and incremental adoption

**DRF**
- [Generic views](https://www.django-rest-framework.org/api-guide/generic-views/) · [ViewSets](https://www.django-rest-framework.org/api-guide/viewsets/) · [Serializers](https://www.django-rest-framework.org/api-guide/serializers/) · [Pagination](https://www.django-rest-framework.org/api-guide/pagination/)
- [DRF Discussion #7850](https://github.com/encode/django-rest-framework/discussions/7850) — why `full_clean()` isn't called

**ORM**
- [Django database optimization](https://docs.djangoproject.com/en/5.2/topics/db/optimization/)
- [Adam Johnson on N+1](https://adamj.eu/tech/2020/09/01/django-and-the-n-plus-one-queries-problem/)

**Celery & Channels**
- [Celery tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html) · [Redis broker](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html) · [Testing with Celery](https://docs.celeryq.dev/en/stable/userguide/testing.html)
- [Adam Johnson, common Celery issues](https://adamj.eu/tech/2020/02/03/common-celery-issues-on-django-projects/)
- [Channels: consumers](https://channels.readthedocs.io/en/stable/topics/consumers.html) · [databases](https://channels.readthedocs.io/en/stable/topics/databases.html) · [testing](https://channels.readthedocs.io/en/stable/topics/testing.html)

**Migrations & testing**
- [Django migrations](https://docs.djangoproject.com/en/5.2/topics/migrations.html) · [writing migrations](https://docs.djangoproject.com/en/5.2/howto/writing-migrations/)
- [django-linear-migrations](https://adamj.eu/tech/2020/12/10/introducing-django-linear-migrations/)
- [pytest-django database docs](https://pytest-django.readthedocs.io/en/latest/database.html)
- [factory_boy](https://factoryboy.readthedocs.io/) · [time-machine vs freezegun](https://adamj.eu/tech/2021/02/19/freezegun-versus-time-machine/)
- [responses](https://github.com/getsentry/responses) · [respx](https://lundberg.github.io/respx/) · [vcrpy](https://vcrpy.readthedocs.io/)
- [pt-online-schema-change](https://docs.percona.com/percona-toolkit/pt-online-schema-change.html) · [gh-ost](https://github.com/github/gh-ost) · [MySQL online DDL](https://dev.mysql.com/doc/refman/8.0/en/innodb-online-ddl-operations.html)

**Config, security, caching, logging**
- [Deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) — what `check --deploy` enforces
- [django-environ](https://django-environ.readthedocs.io/)
- [Django security releases archive](https://docs.djangoproject.com/en/dev/releases/security/) — the authoritative CVE→version mapping
- [DRF permissions](https://www.django-rest-framework.org/api-guide/permissions/) · [DRF throttling](https://www.django-rest-framework.org/api-guide/throttling/)
- [Django caching](https://docs.djangoproject.com/en/5.2/topics/cache/) · [django-redis](https://github.com/jazzband/django-redis)
- [django-structlog](https://django-structlog.readthedocs.io/) · [structlog](https://www.structlog.org/)
- [django-silk](https://github.com/jazzband/django-silk)
