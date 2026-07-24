# NexOps — Ground-Truth Audit Follow-Up: Scope & Attack-Surface Reconciliation

> **STATUS:** COMPLETED (July 24, 2026)  
> **Reconciliation Report:** [NEXOPS_AUDIT_FOLLOWUP_SCOPE_RECONCILIATION_REPORT.md](file:///d:/Projects/ReactJS/NexOps/docs/NEXOPS_AUDIT_FOLLOWUP_SCOPE_RECONCILIATION_REPORT.md)  
> **RLS Table Count:** 11/11 Application Tables RLS-Protected & Forced  
> **Attack Surface Status:** 0 Vulnerabilities Identified (`/execute` sandbox verified, `/insights` RLS verified)  
> **UI Scope:** 4 Sidebar Modules (`/automation`, `/clusters`, `/cicd`, `/graph`) verified functional on live Vercel deploy

Use this as the task brief for the coding agent. This addresses three
findings from `NEXOPS_FULL_GROUND_TRUTH_AUDIT_REPORT.md` that need direct
answers before anything else — landing page work, outreach, or further
GTM steps — proceeds. This takes priority over cosmetic work.

---

## Ground rules

Same standing discipline as every prior pass: real evidence, direct
answers, no claim without it. Given what's being asked here (whether an
unaudited route exists on the live production service), err toward
over-disclosure rather than a reassuring-sounding summary.

---

## Item 1 — Reconcile the RLS table count (7 vs 11)

- List, with real `pg_class` introspection, **every** table in the live
  production schema — not just the 7 checked in the last audit.
- Confirm the status of `workspaces`, `users`, `alerts`, and
  `scoring_weight_recalibrations` specifically — are they still RLS-
  protected as previously verified, or did something change? Show real
  `relrowsecurity`/`relforcerowsecurity` values for each.
- If all four are still correctly protected, state that plainly with
  evidence — this may just be an incomplete list in the last report, not
  an actual regression. Either way, produce the real, complete table.

## Item 2 — Full inventory and audit of `executor` and `insights`

This is the priority item in this document.

- What does the `executor` route actually do? Show the real route
  handler code, every endpoint under it, and what it's capable of. Does
  its name reflect its function (e.g., does it execute anything — code,
  commands, queries)? State plainly, in your own words, what it is.
- Same for `insights` — what does it do, what does it expose or accept as
  input?
- **For both:** are they tenant-scoped? Show the real authorization/
  scoping code, or confirm its absence. If either accepts a workspace-
  or user-addressable parameter, run a real adversarial cross-tenant
  test against it — the same standard applied to every other endpoint in
  the isolation hardening work. If either has no addressable parameter,
  confirm that structurally, same as was done for the integration
  endpoints earlier in this project.
- Were these routes present before the tenant isolation work was done, or
  added afterward? Check git history/blame on the route files. This
  matters: if they existed during the isolation hardening pass and were
  simply missed, that's a real gap in that work's completeness, not a new
  feature to evaluate fresh.
- If `executor` allows anything resembling arbitrary code, command, or
  query execution reachable by an authenticated (or worse, unauthenticated)
  user, flag this as a Priority-A finding immediately at the top of the
  report, before anything else — this is exactly the class of risk this
  project's evidence discipline exists to catch before real users are
  exposed to it.

## Item 3 — Explain the sidebar scope creep (Automation, Clusters, CI/CD, Topology)

- Confirm directly: are these real, functional pages with real backend
  logic behind them, or dead/stub routes that render an empty or
  placeholder view?
- Check git history on `sidebar.tsx` and the associated route files —
  were these ever actually removed per
  `NEXOPS_FRONTEND_RESTRUCTURE_PROMPT.md` and then re-added later, or did
  that restructure never fully apply to begin with?
- **Do not silently remove or fix this** — that's a product-scope
  decision, not a technical one. Just report the real current state
  clearly: what each of these four sections actually does today, with
  screenshots, so the project owner can decide whether to remove them
  (consistent with the original narrow-scope decision) or knowingly keep
  them.

---

## Output format

One report. If Item 2 turns up a real Priority-A finding, put it in a
one-line callout at the very top, before anything else — same convention
used in the tenant isolation hardening report. Otherwise, Items 1–3 each
with real evidence. End with:

> Is there any unaudited, unprotected functionality currently live in
> production that a real user (or attacker) could reach right now? And is
> the current live product scope actually what the project owner intended,
> or has it drifted?
