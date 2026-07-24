# NexOps — Production Data Cutover — Agent Prompt

Use this as the instruction set for Claude Code working **in place** across both
`backend/` and `updated-frontend/`. This is the single most consequential pass in this
project so far: it removes every mock/demo data path and wires the application to real
auth, a real database, and real API calls end to end, in both directions.

**Read this entire document before writing any code.** This prompt has six phases, in a
strict order, with a verification gate at the end of each phase. **Do not start a phase
until the previous phase's gate is confirmed passing.** This is not a suggestion — phases
4 and 5 will silently produce a broken, hard-to-debug app if attempted before phases 1-3
are solid, because the frontend has nothing real to call yet.

Still local/dev only for this pass — no deployment target is being set up yet. "Production
mode" here means **production-grade data and auth handling, running locally**, not
"deployed to a server." Don't add deployment configuration (Docker prod configs, CI/CD,
hosting-specific env setup) in this pass — that's separate, later work.

---

## Ground rules for the whole pass

- **Never delete a mock data file until the real path that replaces it is verified working.**
  Deleting mocks first and fixing wiring second guarantees a broken app with no fallback to
  compare against.
- **Every removed mock value must have a real source identified before removal** — a config
  value, a database row, an API response, or a user input. If you can't identify what real
  thing replaces a given mock value, stop and flag it rather than inventing a plausible-
  looking placeholder, which is exactly the failure mode that produced the original
  root-cause-assignment bug earlier in this project.
- **Show real output at every gate**, not a description of expected behavior — an actual API
  response, an actual database row, an actual rendered page. This project has already caught
  two real bugs (a stubbed root-cause assignment, a duplicate-candidate bug) specifically
  because verification demanded real output instead of summaries. Keep that standard.

---

## Phase 1 — Backend: real environment & secrets, no code logic changes yet

### 1.1 Inventory every mock/dummy/placeholder value
Grep the backend for: `dummy`, `dev-dummy`, `placeholder`, `TODO`, `FIXME`, hardcoded test
credentials, and any `if settings.APP_ENV == "development"` bypass branches (e.g. the
Firebase dev-token bypass from the earlier verification pass). Produce a list — file, line,
what the mock value currently is, what real value/source must replace it. Do not change any
code in this step; this is reconnaissance.

### 1.2 Real environment configuration
- Create a complete `.env.example` listing every required production environment variable
  with a one-line comment describing what it's for (database URL, Firebase service account
  path/credentials, GitHub OAuth client ID/secret, PagerDuty credentials if applicable,
  webhook secret, Redis URL, etc.)
- Confirm `app/core/config.py`'s `Settings` class has no hardcoded fallback values for
  anything security-sensitive (secrets, API keys, tokens) — fallbacks are acceptable only for
  genuinely non-sensitive operational config (e.g. a default request timeout)
- Confirm `APP_ENV` has a real distinction between `development` and `production`, and that
  every dev-only bypass (Firebase dev-token, dummy OAuth fallback, etc.) is unreachable when
  `APP_ENV=production`. Show the exact conditional for each one.

### Gate 1
Show the full `.env.example`. Show that setting `APP_ENV=production` with no dev-token
configured causes a request using the old dummy bypass to be rejected, not silently
succeed. Do not proceed to Phase 2 until this is confirmed.

---

## Phase 2 — Backend: real GitHub OAuth and PagerDuty (or chosen alert source)

### 2.1 GitHub OAuth — go from traced-but-untested to actually working
The previous verification pass confirmed the OAuth code exists but was only statically
traced, with a dummy-token fallback (`access_token = "dummy_github_oauth_token"`) still
present as a silent failure path. This phase requires:
- A real GitHub OAuth App registered (you will need to do this manually outside the agent —
  the agent should pause and ask you for the real `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`
  if they aren't already in your environment, rather than proceeding with the dummy fallback)
- Remove the silent dummy-token fallback in `github_callback` entirely. If the real code
  exchange fails, return a real error to the caller (redirect to a frontend error state, or
  return an HTTP error) — do not fall back to a fake token that lets the app continue in a
  broken-looking-successful state.
- Confirm the exchanged real access token is encrypted at rest using the existing Fernet
  encryption path (already implemented per prior verification) and confirm a real token
  round-trips: store it, then read and decrypt it successfully in a later request.

### 2.2 Real repo sync using the real token
- Confirm `vcs_service.py`'s repo-listing actually calls GitHub's real API using the stored
  real token for at least one real connected account (yours), and that real repos returned
  by GitHub are written into the `repos` table — not seed data.
- Confirm the `nexops.yaml` dependency parser (built in the prior pass) runs against at least
  one real repo with a real `nexops.yaml` file you create for this test, and produces a real
  `Dependency` row.

### 2.3 Real webhook delivery
- Register a real webhook (via the GitHub API, using the real token) on at least one real
  connected repo, pointed at your local backend (use a tunnel tool like ngrok/cloudflared
  if needed for GitHub to reach localhost — note this in the doc as a local-dev-only
  necessity, not a production deployment step)
- Trigger a real event (a real push to the test repo) and confirm a real `Event` row is
  created from a real, signature-verified webhook delivery — not a simulated test payload

### 2.4 PagerDuty (or whatever alert source the backend currently targets)
Apply the same standard: real account, real webhook subscription, real signature
verification if PagerDuty signs its webhooks, a real alert/incident landing in the database
from a real triggered test alert — not seed data.

### Gate 2
Show: a real GitHub account connected through the real OAuth flow (screenshot or terminal
proof of the token exchange succeeding), a real repo list pulled from that account, a real
webhook-triggered `Event` row with its real GitHub payload, and a real alert event ingested
from the chosen alert source. Do not proceed to Phase 3 until all of this is real, not
simulated.

---

## Phase 3 — Backend: remove seed data and mock fallbacks

Only after Phase 2's gate passes:
- Remove or neutralize `seed.py`'s automatic execution on startup (keep the file available
  for local test-database bootstrapping if useful, but it must not run automatically in a
  mode that's supposed to reflect real data)
- Remove the Gemini AI fallback's silent regex/static-text substitution if
  `GEMINI_API_KEY` is unset — replace with an explicit "AI insights unavailable: no API key
  configured" response, so the frontend can show a real unavailable state instead of
  fake-AI-sounding static text that misrepresents itself as a real analysis
- Audit every remaining route for hardcoded demo values (the earlier `INTEGRATIONS_DATA`
  mock array, if anything like it still exists, status fields defaulting to a fixed string
  rather than a real check, etc.) and replace each with a real computed/queried value

### Gate 3
Run the full backend test suite. Confirm it still passes — note that some tests previously
relied on seed data and may need to be updated to use test fixtures created within the test
itself rather than relying on the now-removed automatic seed run. Show the real test output.

---

## Phase 4 — Frontend: replace the mock data layer with real API calls

This is the largest single mechanical change. Go file by file, not all at once.

### 4.1 Map every mock data consumer to its real API endpoint
Produce a table: mock data file/export (e.g. `lib/mock-data.ts`'s `mockIncidents`,
`lib/graph.ts`'s static graph) → which component(s) consume it → which real backend endpoint
now provides that data (per the API surface built in the backend phases above and any prior
backend planning docs in this repo). If a needed endpoint doesn't exist yet on the backend,
stop and flag it — do not invent a frontend call to an endpoint that isn't real.

### 4.2 Replace data fetching, component by component
For each authenticated route (`/dashboard`, `/services`, `/dependencies`, `/incidents`,
`/incidents/[id]`, `/recent-changes`, `/integrations`, `/settings`, `/profile`):
- Replace the static mock import with a real fetch (or whatever data-fetching pattern the
  Next.js app already uses elsewhere — server components with direct fetch, a client-side
  hook, etc. — stay consistent with the existing pattern rather than introducing a new one)
- Add real loading and error states for each fetch — the existing `EmptyState`,
  `CardSkeleton`, `TableSkeleton` components already exist for this; use them rather than
  inventing new loading UI
- Confirm pages that previously had "empty state" handling for empty mock arrays now
  correctly show that same empty state for a genuinely empty real API response — this is
  the moment that logic gets tested for real instead of against a mock `[]`

### 4.3 Replace `feedbackState`'s remaining frontend-only pieces, if any
Confirm the frontend's confirm/reject UI now calls the real
`POST /api/incidents/{id}/feedback` endpoint built earlier, rather than only updating local
React state. Confirm a page refresh after confirming a cause shows the persisted state from
the real database, not a reset-to-mock default.

### 4.4 Auth: replace mock session with real Firebase auth
- Replace the mock `isAuthenticated` boolean/session flag with real Firebase Auth state
  (sign-in via the providers already implied by the login page's UI — GitHub/Google — using
  Firebase's real auth SDK on the frontend)
- The login page's existing loading-state UI (built in an earlier pass) should now reflect
  a real authentication round-trip, not a `setTimeout`-based simulation — remove the
  artificial delay now that there's a real async operation to wait on
- Confirm the existing `AppShell` auth guard logic (checks session + onboarding completion,
  redirects accordingly) now checks real Firebase auth state instead of the mock flag —
  the redirect logic itself should need minimal changes if it was already structured around
  a boolean "is authenticated" check; the source of that boolean is what changes
- Confirm the real authenticated user's identity (from Firebase) is what gets sent as
  credentials on every subsequent API call to the backend, and that the backend's
  `get_current_user` dependency correctly resolves a real user from a real Firebase token

### 4.5 Onboarding: connect to the real OAuth flow
- The onboarding page's "Connect GitHub" button should now trigger the real
  `GET /integrations/github/connect` redirect built in Phase 2, not a mock connect simulation
- The "discovery" animation (staggered node reveal, built in an earlier pass) should now
  reveal real `service_nodes`/`repos` returned from the real sync, not mock graph data —
  keep the animation/staggering behavior, change what data populates it
- Confirm a genuinely new user, connecting a real (test) GitHub account for the first time,
  sees their real repos discovered through this flow

### Gate 4
Click through the entire authenticated app — dashboard, services, dependencies, incidents,
an incident detail page, recent changes, integrations, settings, profile — using a real
logged-in session, with the backend running and connected to real data from Phase 2-3. Show
real screenshots or a description of real rendered content (not mock content) for each page.
Confirm zero remaining imports of `lib/mock-data.ts` or `lib/graph.ts`'s static exports
anywhere in the app.

---

## Phase 5 — Remove the mock data files themselves

Only now, after Gate 4 passes:
- Delete `lib/mock-data.ts`, `lib/graph.ts`'s static mock exports, and any other
  frontend mock data files confirmed to have zero remaining imports
- Delete backend `seed.py` only if you're confident no remaining test relies on it (per
  Phase 3's gate) — otherwise, keep it but clearly marked as test-only tooling, not
  something that runs in any real flow
- Search the entire codebase (both frontend and backend) one more time for the word "mock"
  and review every remaining hit — some may be legitimate (test file names, a clearly-marked
  local-dev fallback that's actually fine to keep), but each one should be a deliberate
  decision at this point, not leftover scope

### Gate 5
Run both the frontend (`npm run build`) and backend test suite one final time. Confirm both
succeed with the mock files gone. Show the real output of both.

---

## Phase 6 — Documentation update

Update `README.md`, `docs/DASHBOARD.md`, and `docs/BACKEND.md` to reflect that the
application now runs on real data end to end — remove any remaining language describing
mock/demo data as the current state. This is the same standard applied after every prior
restructure in this project: stale docs describing a removed mode are a deliverable gap, not
an afterthought.

---

## What NOT to do in this pass

- Do not add deployment/hosting configuration — this stays local/dev-only for now
- Do not add multi-tenancy, roles, or any feature explicitly cut in earlier passes — this
  prompt is about real data plumbing, not new scope
- Do not silently invent a "looks real" fallback for anything you can't actually wire to a
  real source — flag it and stop, the same standard as every gate above

---

## Final definition of done

1. Setting `APP_ENV=production` makes every dev-only bypass unreachable
2. A real GitHub account, connected through a real OAuth flow, populates real repos and a
   real dependency graph
3. A real webhook delivery produces a real event in the database, with real signature
   verification enforced
4. A real alert produces a real candidate-cause correlation with a real, non-mock score
5. The frontend renders real data on every authenticated page, with zero remaining imports
   of the old mock data files
6. Confirming/rejecting a candidate cause persists to the real database and survives a page
   refresh
7. A real user can log in via real Firebase auth, get redirected correctly based on real
   onboarding state, and see their own real data
8. All mock data files are deleted, all tests pass, and documentation reflects the real
   end-to-end state
