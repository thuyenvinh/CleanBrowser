# Backend tests

Tests run against a real PostgreSQL instance — there is no SQLite fallback.
Set `DATABASE_URL` to a Postgres DSN before invoking `pytest`. Schema is
migrated automatically (Alembic `upgrade head`) once per session, and the
`tmp_db` fixture truncates `profiles` / `profile_tags` between tests.

## Local quick start

```bash
# Option A: use the project's docker-compose Postgres service
docker compose up -d postgres
export DATABASE_URL=postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser
PYTHONPATH=. pytest backend/tests
```

```bash
# Option B: any reachable Postgres works
export DATABASE_URL=postgresql://<user>:<pass>@<host>:5432/<db>
PYTHONPATH=. pytest backend/tests
```

If `DATABASE_URL` is unset the suite is skipped (it cannot run safely without
a real database).

## CI

`.github/workflows/ci.yml` provisions a `postgres:16-alpine` service container
and exports `DATABASE_URL` for the `backend-test` job — no extra steps needed.
