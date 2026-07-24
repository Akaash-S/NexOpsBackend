# NexOps Backend — Documentation Generation Prompt

Use this as the instruction set for Claude Code working **in place** on the existing NexOps
backend codebase. Your job is to produce one file: `docs/BACKEND.md`. Do not modify any
backend logic, schema, or configuration — this is a read-and-document pass only.

This should match the rigor of the existing frontend docs (`COMPONENTS.md`, `PAGES.md`) —
those were useful precisely because they cited real file paths and line numbers instead of
describing things in the abstract. Do the same here. A description with no file reference is
not acceptable in this document.

---

## Before writing anything

Read the entire backend directory structure first (`view` the top-level folders, then each
module). Identify the framework, the actual folder layout as it exists today, and which
parts of the planned architecture (if a plan exists in the repo, e.g. a prior `BACKEND_MVP`
doc) have been implemented versus which are still aspirational. Do not assume the planned
architecture was followed exactly — document what's actually there, even if it diverges from
any prior plan.

---

## Required structure for `docs/BACKEND.md`

### 1. Stack & Entry Point
- Framework, language version, key dependencies (from `requirements.txt` /
  `pyproject.toml` / equivalent) — list only what's actually imported and used, not every
  line in the dependency file.
- Application entry point (file + how it's run — uvicorn command, Docker, etc.)
- Environment variables the app actually reads (grep for `os.environ` / `os.getenv` /
  settings classes) — list each one, what it configures, and whether a `.env.example` or
  equivalent exists documenting it.

### 2. Database
- ORM/query layer in use (SQLAlchemy, raw SQL, etc.) and where the connection is configured
- For EVERY table/model that exists in code: table name, file + line where it's defined, every
  column with its type, and any constraints/indexes/foreign keys. Use the actual model
  definitions, not a paraphrase — show the real class/table definition.
- Migration tool in use (Alembic or otherwise) and current migration state — list existing
  migration files in order.
- Explicitly flag: which planned tables (if a prior plan exists in the repo) do NOT exist yet
  in code.

### 3. API Routes
For every route file: list each endpoint with method, path, file + line, request
shape (query params / body schema, citing the actual Pydantic model or equivalent), response
shape, and a one-line description of what it actually does — read the function body, don't
infer from the route name. Explicitly note any route that exists but returns a stub/placeholder
response (e.g. hardcoded data, `NotImplementedError`, a TODO comment) — these are not the same
as a working route and must be labeled differently.

### 4. Ingestion / Webhooks
- For each external integration (GitHub, PagerDuty, or others if present): is there a
  receiver endpoint implemented? File + line. Does it validate the source's signature, or is
  signature validation missing/stubbed? Show the actual validation code or its absence.
- What does the receiver actually do with the payload once received — write to a table
  (which one), trigger a function (which one), or just log/discard it? Trace the real code
  path, not the intended one.
- Is there an OAuth or API-key connect flow implemented for either integration? File + line.
  If it exists, does it actually call the external provider's API, or is it currently mocked/
  stubbed pending real credentials?

### 5. Correlation Logic
- Is there a scoring/correlation function implemented at all? File + line.
- If yes: trace its actual logic — what inputs does it take, what does it compute, does it
  produce a `match_reasons`-style explanation alongside a score, or just a bare number?
  Quote the real scoring logic (the actual point values / conditions), not a summary of what
  it's supposed to do.
- If a blast-radius computation exists: same treatment — file, line, actual logic traced.
- If neither exists yet, state that explicitly rather than describing the planned version as
  if it were built.

### 6. Feedback / State Persistence
- Is there an endpoint or function that writes a confirm/reject decision to the database?
  File + line. Trace whether this actually persists (a real `INSERT`/`UPDATE` against a real
  table) versus being an in-memory placeholder.
- Confirm whether this is wired to read back correctly — i.e., does a GET endpoint for an
  incident actually include the previously-confirmed state from the database, or does it
  always return `confirmed: null` regardless of history?

### 7. Testing & Validation
- List any test files that exist, what they actually cover (by reading test function names
  and bodies, not file names alone), and whether they pass if you run them.
- Note any manual testing artifacts (Postman collections, curl scripts, seed data scripts)
  found in the repo.

### 8. Gaps Summary

Close the document with a single consolidated list — no new analysis, just a pull-together
of every "not yet implemented," "stubbed," or "diverges from plan" flag raised in sections
1–7 above. This section is the most important one: it should let someone read only this
section and know exactly what's real versus what's still aspirational, without reading the
rest of the document.

---

## Rules for this pass

- Cite real file paths and line numbers for every claim. If you can't find a line reference
  for something, that's a signal to investigate further before writing the claim, not to
  write it without one.
- Do not editorialize or grade the implementation in this document — no "this is well done"
  or "this needs improvement." Pure factual documentation. Assessment happens separately,
  after this document exists.
- Do not infer functionality from naming alone (a function called `compute_risk_score` that
  just returns a hardcoded `50` must be documented as returning a hardcoded value, not as "computing
  risk score").
- If something in the codebase contradicts an earlier planning document that also exists in
  the repo, document what the code actually does and do not silently reconcile the
  discrepancy or assume the plan was followed.
- Output only `docs/BACKEND.md`. Do not modify any other file.
