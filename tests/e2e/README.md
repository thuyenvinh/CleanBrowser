# CleanBrowser E2E Tests

End-to-end Playwright suite covering the happy-path flows of the SaaS UI:
auth (signup/login/logout), profile CRUD, proxy CRUD + bulk import, automation
creation, and billing page render.

These tests drive a real browser against a running backend + frontend. They
are intentionally kept lightweight (single worker, sequential) because the
backend uses a single shared Postgres schema.

## Running locally

```bash
# Terminal 1: start backend (FastAPI) on :8080 and Vite dev server on :5173
# from repo root, e.g. docker compose up --build, or:
#   cd backend && uvicorn app.main:app --reload --port 8080
#   cd frontend && npm run dev

# Terminal 2: install + run tests
cd tests/e2e
npm install
npx playwright install chromium
E2E_BASE_URL=http://localhost:5173 npm test
```

If you want to point at the prod-style single-port build (frontend served by
the backend on :8080) just drop `E2E_BASE_URL` — the default is
`http://localhost:8080`.

## Useful commands

```bash
npm run test:headed   # watch a real browser
npm run report        # open the HTML report after a run
npx playwright test specs/auth.spec.ts   # one file
npx playwright test -g "logout"          # by title
```

## CI

The suite runs in `.github/workflows/e2e.yml` (separate job from `ci.yml`).
Triggered manually (`workflow_dispatch`) and on PRs. Postgres is provided as
a service container, backend is started with `uvicorn` in the background, the
frontend build is served by FastAPI on :8080.

## Conventions

- Every test that needs auth signs up a brand-new tenant via
  `helpers/auth-helper.ts::uniqueEmail`, so specs don't leak state between
  one another.
- `apiSignup` is preferred when the test doesn't actually need to exercise
  the signup *form* — saves ~2s of UI per test.
- Selectors prefer accessible roles/labels (`getByRole`, `getByLabel`) over
  CSS — if a test breaks because of a copy change, update the regex.

## Test artifacts

When Playwright tests run, the following are auto-generated:
- **`screenshots/`**: PNG screenshots taken at key steps + on failure
- **`test-results/`**: Videos (.webm) of each test session + trace files
- **`playwright-report/`**: Interactive HTML report — open with `npx playwright show-report`
- **`playwright-junit.xml`**: JUnit XML for CI integration

### View locally

```bash
cd tests/e2e
npx playwright show-report
```

### View traces

```bash
npx playwright show-trace test-results/<test-name>/trace.zip
```

### CI artifacts

GitHub Actions tự upload tất cả artifacts sau mỗi run — vào tab Actions → workflow run → Artifacts section.
