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

Only these fields. Anything else belongs in `.env`.

| Field | Purpose |
|---|---|
| `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` | Git authorship for commits in this identity |
| `GIT_COMMITTER_NAME` / `GIT_COMMITTER_EMAIL` | Committer fields (usually same as author) |
| `GH_TOKEN_KEYCHAIN` | macOS Keychain key name holding this org's GitHub token |
| `CLAUDE_CREDENTIALS_FILE` | Path to a **separate** Claude OAuth credentials file → a separate Claude account/key |
| `GEMINI_CONFIG_DIR` | Optional — separate Gemini CLI config dir for a different Google account |

> The "different Claude key" is just `CLAUDE_CREDENTIALS_FILE` pointing at its own
> file. Each path gets its own `/login`, so a profile can use a different Claude
> subscription/account than your default. On first launch the file is empty and
> Claude Code prompts you to `/login`; the credentials persist there across
> containers.

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

To update it later, add `-U` to overwrite the existing entry. If no entry is
found, the launcher warns and `gh` is simply unauthenticated for that session.

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
3. read GH token from Keychain key "gh-token-claude-ro-work"
4. mount CLAUDE_CREDENTIALS_FILE → container, start container with this identity
5. inside container: git + gh + Claude all use the work identity
```

`.env` is always loaded first; the profile only changes what it names. Without
`--profile`, only `.env` is used (your default identity).

---

## Quick checklist for any new profile

- [ ] `cp env.example env.<name>` and fill in git identity
- [ ] Set `GH_TOKEN_KEYCHAIN` to a unique key name
- [ ] `security add-generic-password ... -s "<that key name>" -w "<token>"`
- [ ] Set `CLAUDE_CREDENTIALS_FILE` to a unique absolute path
- [ ] `./claude.sh --profile <name>` → `/login` to the right Claude account
- [ ] Verify with `git config user.email` and `gh auth status`
