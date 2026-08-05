# React + Next.js App Router Best Practices

Production patterns for React 19 + Next.js 15 App Router with TypeScript, typically
consuming a separate JSON API (Django/DRF, FastAPI) rather than a co-located database.

Companion doc: [django-drf-best-practices.md](./django-drf-best-practices.md).
The two share [§14 The API contract seam](#14-the-api-contract-seam).

For a **client-only SPA** (Vite, no server rendering), use
[bun-vite-react-best-practices.md](./bun-vite-react-best-practices.md) instead —
most of this document is about the server/client boundary, which that stack
doesn't have.

**Version posture (as of 2026-08):** Next.js **16.2.x is the Active LTS**; **15.5.x
is Maintenance LTS**. React 19.2. TypeScript 5.1+ required by Next 16; 5.7 is a
sane floor.

Two warnings that will save you real time:

1. **A version tag on a docs page is not a release announcement.** `nextjs.org`
   pages render with a version tag (e.g. `16.3.0`) that may be a *canary* line —
   16.3 was still canary/preview in late July 2026. Verify against the
   [releases page](https://github.com/vercel/next.js/releases) or a security-release
   post, not the docs tag.
2. **The caching model changed materially between 15 and 16.** §4 documents both
   and labels which is which. Following a 16-era caching guide on a 15.x codebase
   produces configs that build and then fail at runtime.

---

## Table of Contents

1. [The mental model](#1-the-mental-model)
2. [Component boundaries: `use client`](#2-component-boundaries-use-client)
3. [Server Actions and mutations](#3-server-actions-and-mutations)
4. [Data fetching and caching](#4-data-fetching-and-caching)
5. [React 19 primitives](#5-react-19-primitives)
6. [The React Compiler and memoization](#6-the-react-compiler-and-memoization)
7. [State management](#7-state-management)
8. [Routing, layouts, and error handling](#8-routing-layouts-and-error-handling)
9. [Forms and validation](#9-forms-and-validation)
10. [MUI and Emotion under App Router](#10-mui-and-emotion-under-app-router)
11. [Performance](#11-performance)
12. [Auth](#12-auth)
13. [Testing](#13-testing)
14. [The API contract seam](#14-the-api-contract-seam)
15. [Anti-patterns](#15-anti-patterns)
16. [Review checklist](#16-review-checklist)

---

## 1. The mental model

App Router has two module graphs, not one, and they never share an execution
context:

- The **server graph** runs at request time on the server. It can read files, hold
  secrets, and talk to your database or internal API directly.
- The **client graph** is compiled into JavaScript, shipped to the browser, and
  hydrated. It can use state, effects, event handlers and browser APIs.

Everything that trips people up follows from this. As
[Dan Abramov puts it](https://overreacted.io/what-does-use-client-do/), `use client`
does not mean "this runs on the client" — it **exports a reference from the client
graph into the server graph**, so the server can say "render this thing over there"
without ever executing it. `use server` is the mirror image: it exports a function
from the server graph into the client graph as a callable RPC endpoint.

The practical consequences:

- **Only serializable data crosses the boundary** — primitives, plain objects and
  arrays, `Date`, `Map`, `Set`, Promises, JSX, and Server Functions. A regular
  function or a class instance throws at render time.
- **Server Components have no directive.** There is no `"use server"` marker for a
  component. Server is the default; `use client` is the opt-out.
- **Nothing in the client graph can be trusted.** Anything reachable from the
  browser is reachable by a script that isn't your UI.

---

## 2. Component boundaries: `use client`

### The boundary is the import graph, not the render tree

`use client` marks a file. **Every module that file transitively imports joins the
client bundle.** You do not repeat the directive in child components — they're
already in the client graph.

This is why a `use client` in the root layout is catastrophic: it drags the entire
application into the browser bundle and forfeits Server Components entirely.

### Push it to the leaves

Put `use client` on the smallest component that genuinely needs it — the thing with
the `onClick`, the `useState`, the chart library.

```tsx
// ❌ Whole page becomes client-side because of one button
"use client";
export default function BookingsPage({ bookings }) {
  return (
    <>
      <BookingsTable rows={bookings} />   {/* didn't need to be client */}
      <ExportButton onClick={...} />
    </>
  );
}

// ✅ Only the button ships
export default function BookingsPage({ bookings }) {
  return (
    <>
      <BookingsTable rows={bookings} />   {/* stays server */}
      <ExportButton />                    {/* "use client" lives in this file */}
    </>
  );
}
```

### The composition escape hatch

A Server Component passed as `children` (or any prop) to a Client Component is
**not** pulled into the client graph. It renders on the server and arrives as
already-rendered output. This is how you keep a server-rendered subtree inside a
client-side interactive shell:

```tsx
// providers.tsx
"use client";
export function Shell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return <div className={open ? "open" : ""}>{children}</div>;
}

// page.tsx — no directive: this is a Server Component
export default async function Page() {
  const data = await getData();          // runs on the server
  return (
    <Shell>
      <ServerOnlyReport data={data} />   {/* stays on the server */}
    </Shell>
  );
}
```

Apply the same rule to context providers: they must be Client Components, but
render them as deep as possible — wrapping `{children}` in a small provider file,
never wrapping `<html>` with your whole app inside a client component.

### When `use client` is required

Hooks (except `use` and `useId`), event handlers, browser APIs
(`window`, `localStorage`, `IntersectionObserver`), and any library that calls
`createContext`, `forwardRef`, `memo` or `startTransition` at module scope — which
in practice means most component libraries, including MUI (see §10).

### Rules

- ✅ `use client` on the smallest leaf that needs interactivity.
- ✅ Pass Server Components as `children`/props into Client Components.
- ✅ Server Components fetch; Client Components interact.
- ❌ `use client` in a root or segment layout.
- ❌ Marking a component `use server` — see §3, it opens a hole.
- ❌ Passing a callback prop from a Server Component to a Client Component.

---

## 3. Server Actions and mutations

### A Server Action is a public endpoint

`"use server"` turns a function into an RPC endpoint the browser can call. React's
own docs are explicit: **arguments are entirely client-controlled and untrusted**,
and the function is reachable outside the UI flow that was supposed to lead to it.

Therefore, in **every** Server Action, in this order:

```ts
"use server";

export async function cancelBooking(bookingId: string, formData: FormData) {
  // 1. Authenticate — who is calling?
  const session = await getSession();
  if (!session) return { ok: false, error: "unauthenticated" };

  // 2. Validate — never trust the shape or the values
  const parsed = CancelSchema.safeParse({ bookingId, reason: formData.get("reason") });
  if (!parsed.success) return { ok: false, fieldErrors: parsed.error.flatten().fieldErrors };

  // 3. Authorize — may THIS caller act on THIS object?
  //    Delegating to the backend is the correct answer when the backend owns authz.
  const res = await api.post(`/bookings/${parsed.data.bookingId}/cancel/`, parsed.data, {
    token: session.accessToken,
  });
  if (!res.ok) return { ok: false, error: await res.text() };

  revalidatePath("/bookings");
  return { ok: true };
}
```

The authorization check is the one people skip because "the button is only rendered
for admins". The button is not the security boundary.

### Never mark a component `use server`

There is no directive for Server Components. Marking one `use server` makes it a
directly callable endpoint — so if the permission check lives in its *parent*, an
attacker calls the child directly and walks straight past it.

### Don't fetch with Server Actions

React's docs discourage using Server Functions for reads: frameworks process
actions **serially**, and there is no return-value caching. Fetch in Server
Components (or a client data library); use Server Actions for writes.

### Actions vs calling your API directly

With a separate backend API you have a real choice:

| | Server Action | Client fetch to the API |
|---|---|---|
| Secrets | stays on the server | token must be reachable by the browser |
| Network hops | browser → Next → API | browser → API |
| Progressive enhancement | works without JS | no |
| Optimistic UI | `useOptimistic` | data-library mutation |

**Default to Server Actions when a server-held credential (an httpOnly session
cookie, a service token) must not reach the browser**, and to direct client calls
for interactive, high-frequency reads where the extra hop is a real cost. Mixing
both is fine — just be deliberate about which one owns writes.

---

## 4. Data fetching and caching

**This is the section where version matters most.** Read the row for your version
before writing any caching code.

### The two models

| | **Next.js 15.x** | **Next.js 16.x (Cache Components)** |
|---|---|---|
| Config | `experimental.dynamicIO`, `experimental.useCache`, `experimental.ppr` — three separate experimental flags | one `cacheComponents` flag |
| `fetch` default | **not cached** (reversed from the Next 14 default) | dynamic by default; caching is opt-in |
| Opt into caching | `fetch(url, { next: { revalidate: 60 } })`, `unstable_cache` | `'use cache'` + `cacheLife()` |
| PPR | opt-in via `experimental.ppr` + `experimental_ppr` segment config | default behaviour; both flags **removed** |
| `revalidateTag` | `revalidateTag(tag)` | `revalidateTag(tag, profile)` — the one-arg form is deprecated |
| Read-your-writes | — | `updateTag` (Server Actions only) |

Next 16 also requires **Node 20.9+**, ships Turbopack as the default bundler, and
runs the App Router on the React 19.2 canary track.

**Upgrade caveat worth knowing:** PPR in 16 works differently than in the Next 15
canaries, and the Next docs explicitly advise teams already running PPR on a 15
canary to **stay there** rather than upgrade. It's the one place the upgrade guide
counsels against moving.

### If you are on 15.x

The mental model people carry over from Next 14 — "`fetch` is cached by default" —
is **wrong for 15**. Caching is opt-in:

```ts
await fetch(url);                                       // not cached
await fetch(url, { next: { revalidate: 60 } });         // cached, 60s
await fetch(url, { next: { tags: ["bookings"] } });     // cached, tag-invalidated
```

Invalidate with `revalidateTag("bookings")` / `revalidatePath("/bookings")` from a
Server Action or Route Handler after a write.

### If you are on 16.x

Caching is explicit and function-scoped:

```ts
async function getBookings(orgId: string) {
  "use cache";
  cacheLife("hours");
  cacheTag(`bookings-${orgId}`);
  return api.get(`/bookings/?org=${orgId}`);
}
```

`'use cache'` constraints — these bite:

- A cached function **cannot access `cookies()`, `headers()` or `searchParams`**,
  transitively up the call stack. Violating this throws `next-request-in-use-cache`,
  and the failure can pass `next build` yet blow up at runtime.
- The default store is **in-memory per instance** — with multiple replicas behind
  nginx, each has its own cache.
- **Every deploy invalidates all caches**, because the build id is part of the key.
- Unsupported with static export.
- The `default` cacheLife profile is: stale 5 min (client), revalidate 15 min
  (server), expire never. Name a profile explicitly rather than inheriting it by
  accident.

### Three caches, not one

Regardless of version, don't collapse these:

1. **Next's Data Cache** — server-side, persists across requests, what
   `revalidate`/`'use cache'` controls.
2. **React's `cache()`** — per-request memoization on the server. It lives for one
   request only. Arguments are compared with `Object.is`, so passing a freshly
   constructed object defeats it. Define the wrapped function **once** and import
   it — calling `cache(fn)` in two modules creates two independent caches.
3. **The client Router Cache** — the browser's cache of RSC payloads for
   navigation. Configured via `staleTimes`; it is why a client-side back
   navigation can show data your server just revalidated.

### Fetch in Server Components; stream what's slow

```tsx
export default async function Page() {
  // Independent — run concurrently.
  const [summary, bookings] = await Promise.all([getSummary(), getBookings()]);
  return (
    <>
      <Summary data={summary} />
      <Suspense fallback={<TableSkeleton />}>
        <SlowReport />          {/* streams in; doesn't block the shell */}
      </Suspense>
    </>
  );
}
```

**Layout gotcha:** a layout that reads runtime data (`cookies()`, `headers()`, an
uncached fetch) **blocks navigation and will not fall back to a sibling
`loading.tsx`**. Isolate that read behind its own `<Suspense>`, or move it into the
page.

### Rules

- ✅ Fetch in Server Components; `Promise.all` for independent calls.
- ✅ Opt into caching explicitly, and tag it so you can invalidate it.
- ✅ `revalidateTag`/`revalidatePath` after every mutation that changes a cached read.
- ✅ Wrap slow subtrees in `<Suspense>`.
- ❌ Assuming `fetch` is cached (Next 14 muscle memory).
- ❌ Copying a `'use cache'` snippet into a 15.x codebase.
- ❌ Reading cookies/headers inside a cached function.

---

## 5. React 19 primitives

### `useActionState`

```tsx
const [state, formAction, isPending] = useActionState(cancelBooking, { ok: false });
return (
  <form action={formAction}>
    <button disabled={isPending}>Cancel booking</button>
    {state.error && <Alert severity="error">{state.error}</Alert>}
  </form>
);
```

- Returns `[state, dispatch, isPending]`. It replaces the older `useFormState`.
- **Return errors as state; don't throw them.** An unhandled throw escapes to the
  nearest Error Boundary, which is almost never what a form wants.
- `dispatch` must be called inside a Transition or via a form `action` prop, or
  React throws.
- Dispatches queue and process one at a time.

### `useOptimistic`

```tsx
const [optimisticRows, addOptimistic] = useOptimistic(rows, (state, newRow) => [...state, newRow]);
```

- Updates only apply inside an Action or `startTransition`.
- **It auto-reverts on failure** — optimistic state is never persisted, so a failed
  action rolls back with no cleanup code from you.
- Pairs naturally with `useActionState`.

### `useFormStatus`

Lets a nested component (a submit button, a spinner) read the enclosing form's
pending state without prop drilling. It must be a child of the `<form>`, not the
component that renders it.

### `use()`

Consumes a promise or context. Its distinctive power: a Server Component can
**create a promise without awaiting it**, pass it to a Client Component, and let
the client resume it inside Suspense — streaming data across the boundary without
blocking the server render.

```tsx
// server
export default function Page() {
  const slowData = fetchSlowThing();          // NOT awaited
  return <Suspense fallback={<Skeleton />}><Chart data={slowData} /></Suspense>;
}

// client
"use client";
export function Chart({ data }: { data: Promise<Row[]> }) {
  const rows = use(data);                     // suspends here, not on the server
  return <Recharts rows={rows} />;
}
```

Unlike other hooks, `use()` **may be called conditionally**, and it is exempt from
the `use client` requirement.

### `ref` as a prop

React 19 lets function components take `ref` as an ordinary prop. `forwardRef` is
documented as slated for deprecation and removal, but **is not removed yet** — so
existing code keeps working, and migration is mechanical:

```tsx
// Before
const Input = forwardRef<HTMLInputElement, Props>((props, ref) => <input ref={ref} {...props} />);

// After
function Input({ ref, ...props }: Props & { ref?: React.Ref<HTMLInputElement> }) {
  return <input ref={ref} {...props} />;
}
```

`useImperativeHandle` is still correct for exposing a deliberately narrow
imperative API.

---

## 6. The React Compiler and memoization

The React Compiler reached **stable 1.0 on 2025-10-07**. It performs build-time
automatic memoization, and it is intended to replace most manual `useMemo`,
`useCallback` and `memo`.

The rationale is worth knowing because it settles a long-running style argument:
manual memoization was used in only ~8% of PRs at Meta and made those PRs 31–46%
slower to author, with no reliable correctness benefit. The compiler memoizes
everything eligible instead.

**The rules:**

- ✅ **Write new code without manual memoization.** Let the compiler do it.
- ✅ **Enable the compiler** (`reactCompiler` in `next.config`; Next 15.3.1+ is the
  recommended floor).
- ✅ **Use `eslint-plugin-react-hooks@latest`** — it now bundles the Rules-of-React
  lint rules and works standalone. The separate
  `eslint-plugin-react-compiler` is deprecated.
- ❌ **Do not strip existing `useMemo`/`useCallback`/`memo` as a cleanup task.**
  Removing them changes compiled output; the React team explicitly advises against
  a blanket removal pass.

The compiler's correctness depends on your code following the Rules of React. The
lint plugin is therefore not optional — it is the gate that makes automatic
memoization safe.

---

## 7. State management

### The four kinds of state

Most React state confusion is a categorisation failure. Sort state before choosing
a tool:

| Kind | Lives in | Tool |
|---|---|---|
| **Server state** — data owned by the backend | the backend, cached locally | Server Components for first paint; SWR / TanStack Query for client-side reads |
| **URL state** — filters, tabs, pagination, selected row | the URL | `useSearchParams` + router, or `nuqs` |
| **Local UI state** — open/closed, hover, form draft | the component | `useState` / `useReducer` |
| **Global client state** — theme, auth user, feature flags | a provider near the root | Context, or Zustand if it changes often |

**The most common mistake is putting server state into a global store**, then
hand-writing cache invalidation. Server state is remote, shared-ownership and
always potentially stale — that's what a data library solves.

**The second most common is keeping filter/pagination state in `useState`.** Put it
in the URL: it makes the view shareable, bookmarkable, survivable across reload,
and correct with the back button — for free.

### SWR vs TanStack Query

Both are good. **Pick one and never run both** — two bundles and two disconnected
caches means a mutation through one library leaves the other showing stale data.

| | SWR | TanStack Query |
|---|---|---|
| Size / API surface | smaller, fewer concepts | larger, more built-in |
| Reads | `useSWR(key, fetcher)`, dedupes by key, revalidates on focus/reconnect | `useQuery`, same plus richer cache control |
| Mutations & invalidation | `mutate()` — you wire invalidation yourself | `useMutation` + `invalidateQueries` with prefix/fuzzy key matching |
| Pagination | manual | `useInfiniteQuery` |
| Devtools | minimal | strong |

**Default to TanStack Query for a CRUD dashboard**; use SWR when reads dominate,
mutations are few, and you value the smaller surface. Note this head-to-head is a
judgement call — there is no authoritative source that settles it, so it is not
worth an argument or a migration of working code.

TanStack specifics that matter against a paginated DRF API:

- **`invalidateQueries` refetches active queries and marks inactive ones stale**,
  overriding `staleTime`. Key matching is prefix-based by default (`["bookings"]`
  invalidates `["bookings", {page: 2}]`), with `exact` and `predicate` escape
  hatches.
- **There is deliberately no automatic mutation→invalidation link.** For a
  dashboard where nearly every write should refresh nearly every list, a global
  `MutationCache.onSuccess` is the idiomatic answer — global callbacks fire before
  per-mutation ones.
- **`useInfiniteQuery` v5 requires `initialPageParam` and `getNextPageParam`**, and
  DRF's `next` link maps onto it directly — return `undefined` to stop:

```ts
useInfiniteQuery({
  queryKey: ["bookings"],
  initialPageParam: "/bookings/",
  queryFn: ({ pageParam }) => apiFetch<Page<Booking>>(pageParam),
  getNextPageParam: (last) => last.next ?? undefined,   // DRF gives a full URL
});
```

Data arrives as `data.pages` / `data.pageParams`; bound growth with `maxPages`. A
refetch replays pages sequentially from the first — worth knowing before you build
an infinite table over thousands of rows. **v4 docs do not apply to v5** (e.g.
`refetchPage` is gone); check the version on any snippet you copy.

### Forms hold both kinds of state

A form editing server data mixes server state and client state, and the failure
mode is a background refetch overwriting what the user is typing. TkDodo's rule:
**initialize form state from query data once, set `staleTime: Infinity` for that
query while the form is open**, and on successful submit invalidate and `reset()`.

---

## 8. Routing, layouts, and error handling

### File conventions

| File | Role |
|---|---|
| `layout.tsx` | wraps a segment and persists across navigation within it — state is **not** reset |
| `template.tsx` | like a layout but **remounts** on every navigation — use when you need state reset or an enter animation |
| `page.tsx` | the route's own UI |
| `loading.tsx` | Suspense fallback for the segment |
| `error.tsx` | Error Boundary for the segment (must be a Client Component) |
| `global-error.tsx` | catches root-layout errors; **replaces** the root layout, so it must render its own `<html>` and `<body>` |
| `not-found.tsx` | rendered by `notFound()` and for unmatched routes |
| `(group)/` | route group — organises files without adding a URL segment |

### What `error.tsx` does *not* catch

This is the part that surprises people:

- **It does not wrap its own segment's `layout.tsx` or `template.tsx`.** An error
  thrown in `app/dashboard/layout.tsx` is not caught by `app/dashboard/error.tsx`
  — it propagates to the *parent* segment's boundary. Root layout errors need
  `global-error.tsx`.
- **It does not catch errors in event handlers or async code that runs after
  render.** An `onClick` that throws goes nowhere near an Error Boundary. Handle
  it locally, or route it through `startTransition` — errors inside a transition
  *do* bubble to the nearest boundary.
- Since 15.2, `global-error` also displays in development, where it used to be
  masked by the dev overlay.

```tsx
// app/dashboard/error.tsx
"use client";                       // required
export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  useEffect(() => { logToSentry(error); }, [error]);
  return <ErrorPanel onRetry={reset} />;
}
```

In 16.x the boundary also receives a stabilized `retry` prop for re-rendering,
with `reset` narrowed to clearing state.

### Suspense and Error Boundaries are different mechanisms

**Suspense handles loading. Error Boundaries handle errors.** They compose, but
neither substitutes for the other:

- A promise read via `use()` that **rejects** surfaces at the nearest Error
  Boundary and **cannot be caught with try/catch**.
- `React.lazy` throws to the nearest boundary if the chunk fails to load — which is
  a real production event on a deploy that invalidates chunk hashes.
- Suspense does **not** activate for data fetched in Effects or event handlers.

So a robust segment usually needs both a `loading.tsx` (or inline `<Suspense>`) and
an `error.tsx`.

### Known rough edge

Parallel routes (`@slot`) are documented as supporting independent `error` and
`loading` states per slot, but a long-running community bug reports these being
ignored for slot conventions. If you rely on it, verify on your version before
building around it.

---

## 9. Forms and validation

### Return errors, don't throw them

The single most important rule, and it comes from both React and Next: **model
expected errors as return values.** A thrown error in an action cancels queued
actions and escalates to the nearest Error Boundary — so a failed field validation
blows away the whole page instead of showing a red message under an input.

```ts
"use server";
export async function updateBooking(prev: State, formData: FormData): Promise<State> {
  const parsed = BookingSchema.safeParse(Object.fromEntries(formData));
  if (!parsed.success) {
    return { ok: false, fieldErrors: parsed.error.flatten().fieldErrors };  // returned
  }
  const res = await api.patch(`/bookings/${parsed.data.id}/`, parsed.data);
  if (!res.ok) return { ok: false, formError: await readApiError(res) };    // returned
  revalidateTag("bookings");
  return { ok: true };
}
```

State and payload must be **serializable** — they cross the server boundary.

### Which form approach

| Approach | Use when |
|---|---|
| `<form action={serverAction}>` + `useActionState` | the submit is a server-side write, you want progressive enhancement, and validation feedback on submit is enough |
| **react-hook-form + a schema resolver** | rich client-side UX — per-field validation on blur, dependent fields, dynamic arrays, wizards |
| Controlled `useState` | genuinely trivial forms (one or two fields) |

For a dashboard talking to a DRF API, react-hook-form is usually the better fit —
the interactions are rich and there is no progressive-enhancement requirement
behind an authenticated wall. Use Server Actions where a server-held credential
must not reach the browser (§3).

Note: the specific react-hook-form + resolver recommendation is a judgement call —
React's docs don't compare third-party form libraries.

### Validate on both sides, for different reasons

- **Client-side validation is UX.** It gives fast feedback and stops obviously bad
  submissions.
- **Server-side validation is correctness and security.** It is not optional and
  is not made redundant by the client check.
- **The API's validation is the authority.** Your DRF serializer already validates;
  the frontend schema is a convenience copy that *will* drift. Where they disagree,
  the API wins — so always render API field errors back onto the form rather than
  assuming your client schema caught everything.

```ts
// Map DRF's {"field": ["msg"]} onto react-hook-form
for (const [field, msgs] of Object.entries(apiError.fields ?? {})) {
  setError(field as Path<FormValues>, { message: msgs.join(" ") });
}
```

---

## 10. MUI and Emotion under App Router

**MUI components require `use client`.** This is architectural, not a bug: Emotion
generates styles at render time and has no execution model inside Server
Components.

What follows:

- **Your theme file must be `"use client"`** — `createTheme` feeds client machinery.
- **Use `AppRouterCacheProvider`** from `@mui/material-nextjs`. It injects collected
  styles into `<head>` rather than `<body>`, which avoids a flash of unstyled
  content and is measurably faster.
- **Callback-based slot props must live in Client Components.** A function prop
  defined in a Server Component fails serialization at the boundary.
- **Wrap injected styles in `@layer emotion { ... }`** when style precedence
  against another stylesheet matters.
- **Pigment CSS** is MUI's zero-runtime direction and would remove the forced
  client boundary — but it supports App Router via **webpack only, not Turbopack**.
  Given Next's Turbopack default, treat it as not-yet-ready.
- The Pages Router SSR recipe (`@emotion/server`, `extractCriticalToChunks`,
  `_document.tsx`, `hydrateRoot`) is **stale for App Router**. Ignore any guide
  showing it.

**Practical consequence:** in an MUI-heavy dashboard, most of the interactive UI is
client-side no matter what. Don't fight that. Get the value from Server Components
where it's real — data fetching, the page shell, static content, and keeping API
credentials off the browser — rather than trying to make a data grid render on the
server.

---

## 11. Performance

### Where the wins actually are

1. **Ship less JavaScript.** The `use client` boundary is your main lever (§2).
2. **Stream.** Wrap slow subtrees in `<Suspense>` so the shell paints immediately
   instead of the whole page waiting for the slowest query.
3. **Don't waterfall.** Sequential `await`s in one component serialise your
   backend calls:

```tsx
// ❌ two round trips, one after the other
const user = await getUser();
const bookings = await getBookings();

// ✅ concurrent
const [user, bookings] = await Promise.all([getUser(), getBookings()]);
```

4. **Virtualise long lists** before optimising anything else about them.
5. **`next/dynamic`** for genuinely heavy client-only widgets (charts, rich text
   editors, maps) so they don't inflate the initial bundle.

### Streaming behind nginx

Next recommends `X-Accel-Buffering: no` so nginx doesn't buffer streamed responses
— but **that same header disables nginx response caching**. If you serve mostly
cacheable content, the trade goes the other way. Decide per route, and know that
setting it globally in `next.config` silently costs you static-asset caching.

### Measure

`next build` prints per-route bundle sizes — read them; a route that jumped 200 kB
tells you someone imported a library at the wrong level. Use
`@next/bundle-analyzer` when a number looks wrong, and Lighthouse/Web Vitals for
field behaviour. Don't optimise from intuition.

---

## 12. Auth

### Middleware is not an authorization boundary

**CVE-2025-29927** (CVSS 9.1, exploited in the wild) let an attacker skip Next.js
middleware entirely by forging the internal `x-middleware-subrequest` header. Any
app whose authorization lived only in middleware was fully bypassable. It was
fixed in **15.2.3 / 14.2.25 / 13.5.9 / 12.3.5**, and notably **self-hosted
deployments were exposed where Vercel-hosted ones were automatically protected**.

Two things to take from it:

1. **Patch and verify.** Being on a version above the fix line today is not
   sufficient — check whether an earlier vulnerable build ever reached production.
   As defence in depth, strip the header at your reverse proxy:
   `proxy_set_header x-middleware-subrequest "";`
2. **The durable lesson, independent of the CVE:** middleware is for redirects,
   locale, and cheap optimistic checks. **Authorization is re-checked at the data
   boundary** — in every Server Action, every Route Handler, and by the backend
   API itself.

### Where authorization belongs with a separate backend

**The API is the trust boundary. The frontend is not.**

DRF makes the distinction cleanly, and it's the right mental model regardless of
backend framework:

- **Authentication** establishes identity. It "won't allow or disallow" a request —
  it only populates `request.user` / `request.auth`.
- **Authorization** is the permission decision, made server-side at the start of
  the view, against a `request.user` the client **cannot forge**.

So: 401 means authentication failed; 403 means an authenticated caller was denied.
Your frontend consumes those outcomes; it does not make them.

### Session vs token

| | Session cookie | Token (DRF `TokenAuthentication` / JWT) |
|---|---|---|
| Fits | frontend and API on the same site | separate origins, mobile clients |
| CSRF | **required** — the browser attaches the cookie automatically | not applicable in the same way; DRF enforces CSRF only for session-authenticated requests |
| Storage | httpOnly cookie, unreadable by JS | must live somewhere the JS or the Next server can reach |

DRF documents `TokenAuthentication` for client-server setups and **requires HTTPS**
for it. Choosing tokens sidesteps the session-CSRF/SameSite interplay entirely,
which is why it's the common choice for a separately-deployed frontend.

### Handling the credential in Next

**Do not put a long-lived token in `localStorage`.** Any XSS anywhere on the origin
exfiltrates it, and it never expires from the attacker's point of view.

Preferred shape for an App Router frontend:

1. The browser holds an **httpOnly, `Secure`, `SameSite=Lax`** cookie set by your
   auth route — unreadable by JavaScript.
2. **Server Components and Server Actions read that cookie** and attach the
   credential when calling the API, so the token never enters the client bundle.
3. If Client Components must call the API directly, proxy through a Route Handler
   rather than shipping the token to the browser.

Where cookie auth is used cross-site, `SameSite=None; Secure` plus CORS credentials
is required on both ends — and then CSRF protection becomes mandatory again.

Note: the token-storage and refresh-flow specifics here are standard practice
rather than claims traced to a primary source in this research — the sourced part
is the trust-boundary and session-vs-token distinction above.

### The rules

- ✅ Every API endpoint authorizes independently, whatever the UI did.
- ✅ Credentials live in httpOnly cookies or server-side only.
- ✅ Middleware for redirects and cheap optimistic checks only.
- ❌ Authorization decisions in the frontend.
- ❌ Tokens in `localStorage`.
- ❌ Trusting a `role` claim decoded client-side to gate anything that matters.

---

## 13. Testing

### The guiding principle

> "The more your tests resemble the way your software is used, the more confidence
> they can give you." — Testing Library

That is not a slogan, it's a decision procedure. When choosing between two ways to
write a test, pick the one closer to what a user does.

Concretely, from Testing Library's own docs:

- Utilities operate on **DOM nodes, not component instances**.
- **`data-testid` is a fallback**, not a first choice. Query by role, label, then
  text. If you can't find an element by role or label, that's often an
  accessibility bug the test just caught.
- **Don't test internal state or lifecycle methods.** Test rendered output and
  observable behaviour.
- Testing Library is **not a runner** — it sits on top of Jest or Vitest.

### What can and cannot be unit-tested

**Async Server Components cannot be unit-tested** with Vitest or Jest. Next's own
testing guide says so and recommends **E2E for those**. Synchronous Server
Components and all Client Components are unit-testable normally.

That's the practical split:

| Thing | Test with |
|---|---|
| Client Components, hooks, pure logic | Jest or Vitest + React Testing Library |
| Sync Server Components | same |
| **Async Server Components** | Playwright (E2E) |
| Server Actions | extract the logic into a plain function and unit-test that; E2E the wiring |
| Full auth/nav/data flows | Playwright |

The Server Action lesson mirrors the Celery-task lesson on the backend: **keep the
boundary function thin and put the logic somewhere testable.**

### Jest or Vitest

Next.js documents both, so either is a defensible choice.

- **Staying on Jest is fine.** There is no correctness reason to migrate a working
  Jest suite. Migration costs are real and the benefit is speed.
- **Choose Vitest for a new project** — faster, ESM-native, and it shares Vite
  config. Setup needs `@vitejs/plugin-react`, `jsdom`, and `vite-tsconfig-paths`.

This is a preference call; no authoritative source ranks them for App Router.

### E2E with Playwright

- **Isolate every test.** No shared mutable state between tests.
- **Reuse authenticated state via `storageState`** rather than logging in through
  the UI in every test — it is the single biggest E2E speed win.
- Test the handful of flows that would be a crisis if broken (login, the primary
  create/edit path, billing). E2E is expensive; spend it where failure costs most.

### Mocking the API

Mock at the **network boundary**, not by stubbing your own modules — a mocked
`apiFetch` tests your mock, while a mocked network response tests your real client
code including error handling and parsing. MSW is the usual tool.

Keep fixtures honest: generate them from real API responses (or from the OpenAPI
schema) so they drift when the contract drifts.

### What not to test

- **Don't test the framework.** No tests for "does `useState` update", "does Next
  route to `/about`".
- **Don't test implementation details.** If a refactor that changes no behaviour
  breaks the test, the test was wrong.
- **Don't snapshot large component trees.** Nobody reviews a 400-line snapshot
  diff; they run `-u` and move on.
- **Don't chase a coverage number.** Coverage tells you what's untested, not what's
  well tested.

---

## 14. The API contract seam

Rules for the boundary between this frontend and a separate JSON API. The
backend-side counterpart is §14 in
[django-drf-best-practices.md](./django-drf-best-practices.md).

**The backend owns authorization; the frontend owns affordance.** Hiding a button
is UX. It is not a permission check, because the API is reachable without your UI.
Never implement a rule *only* in the frontend, and never assume a frontend check
means the backend doesn't need one.

**Generate types from the API schema; don't hand-maintain them.** If the backend
publishes OpenAPI (drf-spectacular), generate the client types in CI. Hand-written
interfaces drift silently, and the failure mode is a runtime `undefined` in
production rather than a type error at build time.

**Own one API client module.** All calls go through it, so auth headers, base URL,
error normalisation, and retry policy exist in exactly one place:

```ts
// lib/api.ts
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers: withAuth(init?.headers) });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => ({})));
  return res.json();
}
```

**Handle the error envelope the backend actually sends.** Branch on the stable
`code`, never on the human-readable message — messages get reworded and
translated. Render `fields` back onto the form inputs they belong to.

**Money arrives as a string.** Keep it a string, format for display, and never
round-trip it through a JS number — `0.1 + 0.2` is a rounding bug in a billing
system.

**Dates arrive as ISO 8601 with an offset.** Parse once at the boundary; render in
the user's timezone; never build a date by string-slicing.

**Pagination is the API's shape, not yours.** Write one hook that consumes the
backend's envelope, and use it everywhere.

---

## 15. Anti-patterns

| Anti-pattern | Why it's wrong |
|---|---|
| `"use client"` in the root layout | pulls the whole app into the client bundle |
| `"use server"` on a component | makes it a directly callable, unauthorized endpoint |
| Auth check only in middleware | bypassable by design (CVE-2025-29927); not a boundary |
| Server Action without its own authz + validation check | arguments are attacker-controlled |
| Fetching with Server Actions | serial execution, no caching — that's not what they're for |
| Passing a callback prop across the server→client boundary | serialization error at render |
| Sequential `await`s for independent data | needless waterfall; use `Promise.all` |
| Server state in Context/Zustand | you are now hand-writing a cache; use a data library |
| Filter/pagination state in `useState` | unshareable, breaks back button and reload |
| Both SWR and TanStack Query in one app | two bundles, two disconnected caches |
| Stripping `useMemo`/`useCallback` "because the compiler handles it" | changes compiled output; React team advises against |
| `useEffect` to derive state from props | derive during render; effects are for synchronising with outside systems |
| Trusting the pre-15 "fetch is cached by default" mental model | reversed in Next 15 (§4) |
| Following a Next.js guide without checking its version | the docs site runs ahead of released versions |

---

## 16. Review checklist

Boundaries
- [ ] `use client` is on the smallest leaf that needs it — not a layout
- [ ] No callback props crossing server → client
- [ ] Server Components used for data fetching where a credential is involved

Security
- [ ] Every Server Action authenticates, validates, and authorizes — in that order
- [ ] No component marked `use server`
- [ ] Middleware does redirects/UX only; authorization is re-checked at the data layer
- [ ] Next.js is above the CVE-2025-29927 fix line and the proxy strips `x-middleware-subrequest`

Data
- [ ] Independent fetches run concurrently (`Promise.all`)
- [ ] Slow subtrees are wrapped in `<Suspense>`
- [ ] Server state is in a data library, not a global store
- [ ] Filter/sort/page state is in the URL

React 19
- [ ] New code has no manual memoization; `eslint-plugin-react-hooks` is enabled
- [ ] Existing memoization left alone
- [ ] Form errors returned as state, not thrown

Contract
- [ ] All API calls go through the shared client module
- [ ] Errors branch on `code`, not message text
- [ ] Money handled as string; dates parsed once at the boundary

---

## References

**Primary**
- [React: `use client`](https://react.dev/reference/rsc/use-client) · [`use server`](https://react.dev/reference/rsc/use-server) · [Server Components](https://react.dev/reference/rsc/server-components)
- [React: `useActionState`](https://react.dev/reference/react/useActionState) · [`useOptimistic`](https://react.dev/reference/react/useOptimistic) · [`cache`](https://react.dev/reference/react/cache)
- [React Compiler 1.0](https://react.dev/blog/2025/10/07/react-compiler-1)
- [Next.js: composition patterns](https://nextjs.org/docs/app/building-your-application/rendering/composition-patterns)

**Explanations worth reading**
- [Dan Abramov, "What does `use client` do?"](https://overreacted.io/what-does-use-client-do/)
- [joulev, "When not to use `use client` and `use server`"](https://joulev.dev/blogs/when-not-to-use-use-client-and-use-server)

**Security**
- [GHSA-f82v-jwr5-mffw](https://github.com/advisories/GHSA-f82v-jwr5-mffw) — CVE-2025-29927
- [JFrog analysis](https://jfrog.com/blog/cve-2025-29927-next-js-authorization-bypass/)

**MUI**
- [MUI Next.js integration](https://mui.com/material-ui/integrations/nextjs/) · [MUI on App Router](https://mui.com/blog/mui-next-js-app-router/)
