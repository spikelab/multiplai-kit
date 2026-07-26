# Security Policy

## Supported versions

This repo has **no release tags and no LTS**. The supported version is the
current `main` — users consume it by tracking it (`git pull && ./setup.sh`).
Fixes land on `main`; there are no backports. If you are running an older
checkout, update before reporting.

| Version | Supported |
|---|---|
| `main` (latest) | ✅ |
| any older checkout | ❌ — update first |

## Reporting a vulnerability

Email **security@spikelab.org**. Please do **not** open a public GitHub issue
for anything exploitable.

Include: what you did, what happened, what you expected, and the commit SHA
(`git rev-parse HEAD`) of the checkout you hit it on. A proof of concept helps.

- **Acknowledgement:** within 5 business days.
- **Assessment and a plan (or a "won't fix" with reasoning):** within 14 days.
- **Disclosure:** coordinated — please give us a chance to ship a fix on `main`
  before publishing. This is a small project run by one maintainer; the windows
  above are honest estimates, not an SLA.

Do not include live credentials, tokens, or private session transcripts in a
report — describe them instead.

## Threat model

The kit's security posture is documented in the README, and those sections are
the authoritative version — this file deliberately does not restate them, so
there is only one copy to keep true:

- [**What credentials enter the container**](README.md#what-credentials-enter-the-container)
  — the complete list of what is mounted or forwarded, when, and the blast
  radius of each.
- [**Network egress**](README.md#network-egress) — what `--net` does and does
  not do today.
- [**Data & retention**](README.md#data--retention) — what is written to disk,
  where, and for how long.

The one line that governs everything else:

> **The container is the permission boundary.** Sessions run with
> `--dangerously-skip-permissions` because the container — not the
> permission prompt — is the sandbox. Consequently **anything mounted into or
> forwarded into the container is reachable by the agent, and by any prompt
> injection that lands in a page it fetches, a repo it reads, or an email it is
> shown.** Decide what to hand over before you hand it over.

What follows from that:

- **In scope** for a report: the container escaping or weakening its own
  boundary (privilege escalation, `--cap-drop`/`no-new-privileges` bypass);
  credentials entering the container that the README says do not, or entering
  when their gate (`MULTIPLAI_SKILL_SECRETS`, `MULTIPLAI_MOUNT_GEMINI`,
  `--gcp`) is off; secrets written into the image, into git, or into a log;
  `guard_destructive.py` failing to deny a command it claims to deny;
  `setup.sh` / `claude.sh` executing untrusted input from the workspace or a
  fetched artifact; the container pin being resolvable to something other than
  the immutable tag in `CONTAINER_REF`.
- **Not a vulnerability**, because it is the documented design: the agent
  reading or writing any file in the mounted workspace; the agent using a token
  you chose to forward; a prompt injection in fetched content causing the agent
  to act within the permissions you already granted it. The mitigations for
  these are scoping (fine-grained `GH_TOKEN`, `ssh-add -D`, narrowing
  `MULTIPLAI_SKILL_SECRETS`), not a code fix here.
- The kit has **no telemetry** and phones nothing home. A report showing
  otherwise is very much in scope.

Vulnerabilities in the sibling repos belong there:
[`multiplai-container`](https://github.com/spikelab/multiplai-container) (image,
host SSH gateway) and
[`multiplai-cc-mktplace`](https://github.com/spikelab/multiplai-cc-mktplace)
(the plugins, including `multiplai-context`). When in doubt, mail the address
above and we will route it.
