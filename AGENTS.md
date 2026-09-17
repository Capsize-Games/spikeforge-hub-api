# Agent guide — spikeforge-hub-api

Instructions for any coding agent working in this repository.

## Read these first

- The design of record is **`plans/hub_accounts_plan.md` in the
  [spikeforge](https://github.com/capsize-games/spikeforge) repository**. Every
  limit, state machine, and trust label in this service is a decision recorded
  there. Changing one of those defaults is a policy change, not a tuning knob.
- `spikeforge`'s **`rules.md`** governs the code style here too: no file over
  250 lines, no class over 200, no function over 20, one class per file, 79
  columns, type hints and docstrings on every signature.
- `spikeforge`'s **`COPY_POLICY.md`** governs any user-visible string,
  including error messages. An error that does not name the limit it hit is a
  support request rather than an answer.

## Prohibited shortcuts

No `# noqa`, no `type: ignore`, no stubs or monkeypatches. `ruff` and
`mypy --strict` are both clean and are expected to stay that way; if one
complains, the fix is the underlying issue.

## Invariants this service exists to hold

1. **No artifact byte is ever written to the host's root disk.** It has under
   a gigabyte free. Artifacts and the database data directory are bind mounts
   onto the attached volume; nothing persistent uses a Docker named volume.
2. **No upload is ever buffered in memory.** The host has roughly a gigabyte
   of available RAM, shared with six other projects. Bytes stream to disk, and
   the size cap is enforced *during* the stream, not only from
   `Content-Length`, which is a client claim.
3. **The footprint cap and free-space floor are load-bearing.** The volume's
   other tenant is a growing video library. Per-account quotas are fairness
   between users; those two numbers are a promise to the machine and are
   enforced structurally at upload intent, not monitored.
4. **Nothing here loads a model.** No `torch` dependency, ever. Verification
   runs in an ephemeral sandbox elsewhere, because running `torch.load` on
   user-supplied bytes on this host would put six other projects' credentials
   behind it.
5. **Only measured facts are stored as facts.** A client's declared digest and
   size are assertions, checked against bytes this service hashed itself. A
   manifest or accuracy claim is only ever recorded from bytes we read.
6. **The trust vocabulary is `machine-checked` and `unchecked`.** There is no
   `verified` label, because this service cannot earn that word. Interface
   copy must not imply otherwise.

## Verification

```bash
ruff check .
mypy hub_api
pytest -q                                    # SQLite
HUB_TEST_DATABASE_URL=postgresql+psycopg://... pytest -q --no-cov
```

The PostgreSQL run is not optional busywork: SQLite cannot catch a dialect
difference, and the schema has two places one could hide — the JSONB variant
and the timezone-aware timestamp decorator. The decorator exists because
SQLite returns naive datetimes from a `timezone=True` column and PostgreSQL
does not, which made a comparison fail on one and silently pass on the other.

## Commits and pull requests

Do not add AI vendor branding, "generated with" footers, session links, or AI
co-author trailers. Do not claim human review or human-executed testing that
did not happen. Describe what was actually run, including anything skipped.
