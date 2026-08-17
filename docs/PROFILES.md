# Profiles — Setting Up a New Work Identity

A **profile** lets you launch the kit under a separate identity: its own git
author/committer, its own GitHub token, and its own Claude account. Use one per
client or employer so commits, GitHub access, and Claude usage stay cleanly
separated (e.g. `work`, `personal`).

A profile is a single overlay file — `env.<name>` — sourced **after** `.env`,
so it overrides specific fields while everything else (workspace path, skill API
keys, container settings) still comes from `.env`. Profile files are gitignored;
each machine keeps its own.

Launch with: `./claude.sh --profile <name>`

---

## What a profile can override

A profile may set **any** variable — it is sourced after `.env` under the same
rules, so whatever it names wins over `.env` and is forwarded to the container
when non-empty. In practice these are the fields worth putting in one, because
they are the ones that differ per identity. Everything else belongs in `.env`,
where it applies to every launch.

| Field | Purpose |
|---|---|
| `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` | Git authorship for commits in this identity |
| `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL` | Committer fields (usually same as author) |
| `GH_TOKEN_KEYCHAIN` | macOS Keychain key name holding this org's GitHub token |
| `GH_TOKEN_APP` | **Instead of the above** — name of a host-side GitHub App profile; the session mints a fresh ~1h installation token per launch. Exclusive with `GH_TOKEN`/`GH_TOKEN_KEYCHAIN`; see "One identity per profile" below |
| `CLAUDE_CREDENTIALS_FILE` | Path to a **separate** Claude OAuth credentials file → a separate Claude account/key |
| `GEMINI_CONFIG_DIR` | Optional — separate Gemini CLI config dir for a different Google account |
| `GCP_KEY_FILE` / `CLOUDSDK_CORE_PROJECT` | Optional — a service-account key that should follow this client rather than apply to every launch |

> The "different Claude key" is just `CLAUDE_CREDENTIALS_FILE` pointing at its own
> file. Each path gets its own `/login`, so a profile can use a different Claude
> subscription/account than your default. On first launch the file is empty and
> Claude Code prompts you to `/login`; the credentials persist there across
> containers.

---

## One identity per profile — where the GitHub token lives

There are two ways to authenticate GitHub, both supported, **never both at once**:

| Mode | Config | Use when |
|---|---|---|
| **PAT** | `GH_TOKEN`, or `GH_TOKEN_KEYCHAIN` naming a Keychain item | the org has no GitHub App — the default |
| **App** | `GH_TOKEN_APP=<app>` | macOS + host bridge, and you installed a GitHub App for the org. Each launch mints a fresh ~1-hour installation token; the App's private key never enters the container. Setup: `container/docs/gh-app-token.md` |

Declaring one of each **in configuration** is a hard launch error, not a
precedence rule:

```
Error: two GitHub identities are declared in configuration.
         GH_TOKEN_APP='dolce'   declared in env.dolce
         GH_TOKEN               declared in .env
```

They select different GitHub identities, and a silent winner means running the
session as the wrong user — worse than not launching.

**The consequence for your file layout is not optional.** A `GH_TOKEN` sitting
in `.env` as a global default conflicts with *every* profile that sets
`GH_TOKEN_APP`. So each identity's GitHub auth belongs in **its own profile**,
and `.env` carries neither:

```
.env            → WORKSPACE, API keys, container settings.  No GitHub token.
env.spikelab    → GIT_* identity + GH_TOKEN_KEYCHAIN="gh-token-spikelab"
env.dolce       → GIT_* identity + GH_TOKEN_APP="dolce"
```

One exception, by design: a **shell** export is an override, not a conflict —
in either direction. `GH_TOKEN=$(mint) ./claude.sh --profile dolce` launches,
uses that token, and leaves the App hooks inert for that session; a shell
`GH_TOKEN_APP=<app>` likewise beats a file-declared PAT. The same "your shell
wins" rule that applies to every other variable — and never silently: the
launcher prints a notice naming the variable being dropped and the file that
declared it.

In App mode the launcher forwards no `GH_TOKEN` at all (an environment token
beats gh's credential store and would block it), and there is **no PAT
fallback**: if minting fails you get an unauthenticated `gh` (with the mint
retried at most once a minute), not a silent switch to a different identity.

---

## Profiles can select a different image

A profile may set `IMAGE_NAME` to launch its sessions in a project **overlay
image** — the base image plus project-specific tooling, from a Dockerfile kept
in that project's repo (see the multiplai-container README, "Overlay images").

Register the overlay once in `overlays.conf` at the kit root
(`cp overlays.conf.example overlays.conf`):

```
myproject:PROJECTS/myproject/claude-overlay
```

`./setup.sh` (via `container/build.sh`) then rebuilds the base **and** every
registered overlay — tagged `claude-multiplai-<name>:local` — on every run;
unchanged entries are Docker-cache no-ops. Point the profile at the tag:

```bash
# env.myproject
IMAGE_NAME="claude-multiplai-myproject:local"
```

The launcher applies its `claude-multiplai:local` default only after sourcing
profiles, so the profile value wins. `IMAGE_NAME` configures the launcher only
and is never forwarded into the container. At launch the launcher compares the
overlay's recorded base-image ID against the current base and warns when the
overlay has been left behind on an older base — re-running
`cd container && ./build.sh` (or `./setup.sh`) catches it up.

---

## Step-by-step: create a new profile

Example below uses `work`. Substitute your own name/email/token.

### 1. Create the profile file

```bash
cd multiplai-kit
cp env.example env.work
```

Edit `env.work`:

```bash
GIT_AUTHOR_NAME="Your Name"
GIT_AUTHOR_EMAIL="you@example.com"
GIT_COMMITTER_NAME="Your Name"
GIT_COMMITTER_EMAIL="you@example.com"
GH_TOKEN_KEYCHAIN="gh-token-claude-ro-work"
CLAUDE_CREDENTIALS_FILE="$HOME/.claude-container/credentials-work.json"
# GEMINI_CONFIG_DIR omitted → uses the shared default ~/.gemini
```

Notes:
- `CLAUDE_CREDENTIALS_FILE` must be an **absolute path**. Use `$HOME/...` (it's
  expanded when the file is sourced) — not `~`.
- Omit any field you don't want to override; the `.env` default is kept.

### 2. Store the GitHub token in Keychain

The launcher reads the token from macOS Keychain by the key in
`GH_TOKEN_KEYCHAIN` (it never stores the token in a file). Create a fine-grained
or read-only PAT for the work org, then:

```bash
security add-generic-password \
  -a "$USER" \
  -s "gh-token-claude-ro-work" \
  -w "<paste-the-github-token>"
```

To update it later, add `-U` to overwrite the existing entry. If the named
entry does not resolve, the launcher warns and `gh` is simply unauthenticated
for that session. The Keychain is only probed when `GH_TOKEN_KEYCHAIN` names an
item — with no GitHub auth configured at all, the launcher stays silent, and it
never looks in the Keychain it was not pointed at. The launcher used to read an
item named `gh-token` implicitly; it no longer does. Set
`GH_TOKEN_KEYCHAIN="gh-token"` to keep using that item.

> **Keychain lookups fail from SSH sessions** — the login keychain is locked
> there, so `security find-generic-password` returns nothing even for an item
> that exists. When launching over SSH, use `GH_TOKEN` in `.env` (or the
> profile) or App mode instead.

### Any secret can live in the Keychain — the `*_KEYCHAIN` convention

`GH_TOKEN_KEYCHAIN` is not special. **`FOO_KEYCHAIN=<item>` means: look `<item>`
up in the login Keychain and export the result as `FOO`** — for every variable.
So a per-identity API key can stay out of the profile file entirely:

```bash
security add-generic-password -a "$USER" -s "anthropic-key-work" -w "sk-ant-..." -U
```

```bash
# env.work
ANTHROPIC_API_KEY_KEYCHAIN="anthropic-key-work"
```

and the session receives `ANTHROPIC_API_KEY`.

| | |
|---|---|
| **Precedence** | An explicitly set `FOO` wins. `FOO_KEYCHAIN` is consulted only when `FOO` is empty, so `FOO=x ./claude.sh` still overrides for one launch |
| **The lookup** | `security find-generic-password -a "$USER" -s <item> -w`. The item must be stored under your own account |
| **Forwarding** | `FOO_KEYCHAIN` is never forwarded — it names an item in a Keychain the container cannot reach. The resolved `FOO` is what crosses |
| **Failure** | One warning listing every variable affected, then the launch proceeds. A missing optional secret must not stop a session |

The single-warning rule matters over SSH: the login keychain is locked there, so
every lookup fails at once and five secrets would otherwise mean five identical
walls of text.

`GH_TOKEN` is the one exception, and only in App mode: with `GH_TOKEN_APP` in
play the launcher will not resolve `GH_TOKEN` from the Keychain, because a PAT
appearing behind an App would swap the session's GitHub identity without saying
so. Every other variable resolves normally in App mode.

### 3. First launch → log into the right Claude account

```bash
./claude.sh --profile work
```

On first run the credentials file (`credentials-work.json`) is empty, so
Claude Code prompts `/login`. Sign in with the Claude account you want this
profile to bill against. Subsequent launches reuse it automatically.

### 4. Verify the identity

Inside the session (or `./claude.sh --profile work --shell`):

```bash
git config user.name && git config user.email   # → Your Name / you@example.com
gh auth status                                   # → authenticated via the work token
```

The container is also named `claude-work-<suffix>` so you can tell
profiles apart in `docker ps` / OrbStack.

---

## How it fits together (launch flow)

```
./claude.sh --profile work
  ↓
1. source .env              # WORKSPACE, default git identity, skill API keys
2. source env.work          # overrides git identity, GH_TOKEN_KEYCHAIN, CLAUDE_CREDENTIALS_FILE
3. anything exported in your shell wins over BOTH files
4. pick the GitHub auth mode — PAT (read the token from Keychain key
   "gh-token-claude-ro-work" unless already set) or App (forward GH_TOKEN_APP
   and no token; refuse if both were declared in files)
5. mount CLAUDE_CREDENTIALS_FILE → container, forward every non-empty declared var
6. inside container: git + gh + Claude all use the work identity
   (in App mode, a SessionStart hook mints the token and stores it in gh's
   credential store; a PreToolUse hook renews it when it runs out)
```

`.env` is always loaded first; the profile only changes what it names. Without
`--profile`, only `.env` is used (your default identity).

Step 3 is worth remembering: the files are defaults, and your shell overrides
them. So you can borrow one field of another identity for a single launch —
`GIT_AUTHOR_EMAIL=me@personal.example ./claude.sh --profile work` — without
editing either file.

---

## Quick checklist for any new profile

- [ ] `cp env.example env.<name>` and fill in git identity
- [ ] Pick **one** GitHub auth mode for this profile, and keep the other out of
      `.env` too:
  - PAT → set `GH_TOKEN_KEYCHAIN` to a unique key name, then
    `security add-generic-password ... -s "<that key name>" -w "<token>"`
  - App → set `GH_TOKEN_APP="<app>"` and make sure
    `~/.local/state/multiplai-gh-token/<app>/` exists
    (`multiplai-gh-token --check <app>`)
- [ ] Set `CLAUDE_CREDENTIALS_FILE` to a unique absolute path
- [ ] `./claude.sh --profile <name>` → `/login` to the right Claude account
- [ ] Verify with `git config user.email` and `gh auth status`
