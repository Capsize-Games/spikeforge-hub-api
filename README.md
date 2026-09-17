# spikeforge-hub-api

Accounts, storage quotas, and community model hosting for
[spikeforge](https://github.com/capsize-games/spikeforge).

A person signs up at `hub.spikeforge.net`, signs in from the desktop app,
gets a bounded amount of hosted storage, and publishes a `.spkf` bundle that
anyone else can find and download.

The design of record is
[`plans/hub_accounts_plan.md`](https://github.com/capsize-games/spikeforge/blob/main/plans/hub_accounts_plan.md)
in the spikeforge repository. Every limit and state machine here is a decision
recorded there.

> **Pre-1.0 and not yet deployed.** The verification sandbox (the part that
> would let an artifact be labelled `machine-checked`) is not built, and the
> obligations that come with accepting user accounts and user content — terms,
> privacy policy, deletion path, takedown process — are not in place. Those
> are launch blockers, not follow-ups.

## What it is not

It never loads a model and has no `torch` dependency. It stores bytes,
accounts for them, and indexes what was published. Inspecting an artifact
happens in an ephemeral sandbox elsewhere, because running `torch.load` on
user-supplied bytes on the production host would put six other projects
behind it.

## Identity

Email and password, plus any OAuth2 provider the deployment enables. Both
routes converge on one account, so an account created through GitHub can
later set a password and an account created with a password can link
providers — provider links live in their own table rather than as a column
per provider, so offering one more is configuration and not a migration.

The password layer, the OAuth2 flow, and the token primitives come from
[capsize-auth](https://github.com/capsize-games/capsize-auth). Presets ship
for GitHub, Google, GitLab, Discord, Twitch, Microsoft and ORCID; enable
them by registering credentials:

```
HUB_OAUTH_PROVIDERS={"github": ["client-id", "secret"], "orcid": [...]}
```

`GET /v1/auth/providers` then lists exactly what will work, which is what a
sign-in page should render.

Credentials are opaque and stored only as a SHA-256 — not JWTs. A personal
access token has to be revocable the moment someone pastes one into a public
repository, and a stateless token cannot be.

## Storage and quotas

Uploads are two-phase, and the order is the point:

```
POST /v1/uploads                    → every check that can be made from
                                      metadata, then a reservation
PUT  /v1/uploads/{id}/content       → bytes, streamed and hashed on arrival
POST /v1/uploads/{id}/commit        → published, or sent for verification
```

A caller is refused *before* spending bandwidth. The declared digest and size
are assertions, checked against what this service measured itself. Bytes
never accumulate in memory, the size cap is enforced during the stream rather
than trusted from `Content-Length`, and a partially written artifact is never
reachable under its final name.

Artifacts are content-addressed, so identical bytes are stored once — but each
owner is still charged, so one account deleting cannot silently unshare
another's.

The ledger records only bytes actually stored. A reservation is not a ledger
row; it is the reserved version row itself, which carries a size and an
expiry. So an abandoned upload stops counting against an allowance the moment
it expires, with no compensating entry and no window where a crashed request
leaves a permanent charge.

Two limits protect the host rather than the user: a service-wide footprint cap
and a free-space floor, both checked at upload intent. The volume this runs on
has another tenant, and a hub that fills it would take that tenant down.
Per-account allowances may oversubscribe the cap deliberately — they are
fairness between users; the cap is a promise to the machine.

## Trust labels

`machine-checked` means the bundle's checksums matched, it loaded with
weights-only deserialisation, it produced a NIR graph, the drift check passed,
and an energy report was generated. It does **not** mean the accuracy claim
was reproduced, the licence was read by a human, or the model is any good.

`unchecked` means stored and checksummed on arrival, and nothing more.

There is no `verified` label, because this service cannot earn that word.

Community uploads live at `@handle/slug` and are never promoted into the
curated catalog, whose value is that every claim in it has been checked. The
curated prefixes are reserved handles, so nothing can publish under a name
that reads like a curated entry.

`GET /v1/index.json` renders the published namespace in the *exact* schema
`spikeforge_hub.catalog` already validates, with `source: "community"`. The
client needs no second code path, and a malformed hosted entry is reported
through its existing `issues()` rather than dropped.

## Running it

```bash
pip install -e ".[dev]"
export SPIKEFORGE_HUB_TOKEN_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
export SPIKEFORGE_HUB_DATABASE_URL=postgresql+psycopg://user:pass@localhost/hub
alembic upgrade head
python -m hub_api
```

`.env.example` documents every setting. There is no fallback signing secret:
one that reaches production is indistinguishable from having none.

## Tests

```bash
pytest -q                        # SQLite, no services needed
mypy hub_api && ruff check .
```

Against the deployment's actual database:

```bash
docker run -d --rm --name hub-pg -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=hubtest -p 55432:5432 postgres:16-alpine
HUB_TEST_DATABASE_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/hubtest \
  pytest -q --no-cov
```

Both runs are in CI. The PostgreSQL one is not busywork: SQLite cannot catch a
dialect difference, and the schema has two places one could hide. The
timezone-aware timestamp decorator exists because SQLite returns naive
datetimes from a `timezone=True` column while PostgreSQL does not, which made
one comparison raise on SQLite and silently pass on PostgreSQL.

## Deployment

`compose.yaml` runs the service and its database on the shared host, behind
the Caddy that already terminates TLS there, publishing no host port.
`deploy/hub.Caddyfile` holds the site blocks.

Nothing persistent uses a Docker named volume: those live on a root disk with
under a gigabyte free. Artifacts and the database data directory are absolute
bind mounts onto the attached volume.

## Licence

BSD-3-Clause, matching spikeforge. See [LICENSE](LICENSE).
