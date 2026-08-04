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

---

## 9. Settings, configuration, secrets

<!-- GAPFILL:settings -->

---

## 10. Security

<!-- GAPFILL:security -->

---

## 11. Caching

<!-- GAPFILL:caching -->

---

## 12. Logging and observability

<!-- GAPFILL:logging -->

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

<!-- GAPFILL:testing-http -->

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

<!-- GAPFILL:testing-ci -->

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
