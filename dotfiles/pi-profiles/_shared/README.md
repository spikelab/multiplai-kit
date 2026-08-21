# Shared pi profile defaults

Seeded into **every** profile. Files here mirror `~/.pi`, so `web-search.json`
lands at `~/.pi/web-search.json`. The profile's own template is copied first, so
a profile can override anything here by shipping the same path.

`packages.txt` and `required-env.txt` are read by `scripts/pi-bootstrap.sh` and
are never copied into `~/.pi`.

## `web-search.json` — why `githubClone` is off

`pi-web-access` clones GitHub repositories to disk when the agent fetches a
github.com URL. That code path is unsafe in 0.24.0, and the container does not
contain it, because the workspace is bind-mounted at the same absolute path
inside and outside — a delete under `/Users/spike/...` from in here removes the
real file.

Verified by reading `github-extract.ts` in the installed package:

- `decodeURIComponent(segment)` (line 145) percent-decodes each path segment of
  the URL with no character-set validation, so `%2E%2E%2F` becomes `../`.
- `cloneDir()` (line 186) is `join(config.clonePath, owner, dirName)` — the
  decoded `owner` is joined with no containment check, and `join` resolves `..`,
  so the result can escape `/tmp/pi-github-repos`.
- `cloneRepo()` (line 290) then runs
  `rmSync(localPath, { recursive: true, force: true })` **before** cloning.

The host check passes because the host genuinely is github.com. The trigger is
the agent fetching a crafted link — which is exactly what this extension does
with links it finds, so the attacker only needs a page the agent reads.

`enabled: false` is checked at the top of the clone entry point
(`if (!config.enabled) return null;`, line 611) before any path is built or
removed, so it closes the path completely and returns `null` rather than
throwing.

**What this costs:** the extension will not clone repositories. Reading GitHub
through the API is a separate module (`github-api.ts`) with no reference to this
gate, so issues, READMEs and file contents still work. For a real checkout, use
`git clone` or `gh repo clone` from pi's bash tool — which is you asking for a
named repo, not a URL the agent happened to read.

Re-enable only once upstream has fixed the traversal.
