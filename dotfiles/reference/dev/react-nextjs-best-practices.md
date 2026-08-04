# React + Next.js App Router Best Practices

Production patterns for React 19 + Next.js 15 App Router with TypeScript, typically
consuming a separate JSON API (Django/DRF, FastAPI) rather than a co-located database.

Companion doc: [django-drf-best-practices.md](./django-drf-best-practices.md).
The two share [§14 The API contract seam](#14-the-api-contract-seam).

For a **client-only SPA** (Vite, no server rendering), use
[bun-vite-react-best-practices.md](./bun-vite-react-best-practices.md) instead —
most of this document is about the server/client boundary, which that stack
doesn't have.

**Version anchor:** React 19.2, Next.js 15.5, TypeScript 5.7 strict.
Next.js documentation on the web is currently versioned ahead of 15.x, and several
caching and rendering behaviours differ between 15 and 16 — §4 labels which is
which. **When in doubt, check the changelog for your pinned version, not the docs
site.**

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

<!-- GAPFILL:caching -->

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

<!-- GAPFILL:state -->

---

## 8. Routing, layouts, and error handling

<!-- GAPFILL:routing -->

---

## 9. Forms and validation

<!-- GAPFILL:forms -->

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

<!-- GAPFILL:auth -->

---

## 13. Testing

<!-- GAPFILL:testing -->

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
