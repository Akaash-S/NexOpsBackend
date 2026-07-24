# NexOps — Manual Closeout Checklist (Pre-GTM)

> **STATUS:** COMPLETED (July 24, 2026)  
> **Closeout Report:** [NEXOPS_MANUAL_CLOSEOUT_REPORT.md](file:///d:/Projects/ReactJS/NexOps/docs/NEXOPS_MANUAL_CLOSEOUT_REPORT.md)  
> **Alembic Revision Confirmed:** `c1a2b3c4d5e6` on Neon production DB  
> **Redis Connection Hardened:** `health_check_interval=30`, `socket_keepalive=True` in `redis.py` (`commit c67bb98`)

Companion to `NEXOPS_MASTER_STATUS_V4.md`, Sections 3 and 4. These two
items are the only things left before the project can be treated as fully
closed out on the technical/verification side — neither is agent work,
both are quick, direct checks/actions for the project owner.

---

## 1. Confirm Alembic's real status

**Why:** V3 recorded Alembic as still deferred. The ledger/recalibration
work since then used a real Alembic revision
(`a8f9c2d1b4e7`) through the full three-tier migration workflow — strong
evidence Alembic is now actually in use, but V4 flagged this as inferred,
not directly confirmed.

**Check directly:**
- [ ] Does `backend/alembic/` exist in the repo, with a real `env.py` and
      `versions/` directory?
- [ ] Does a live `alembic_version` table exist in each of the three Neon
      branches (migration / staging / production), and does its value
      match the latest real revision ID?
- [ ] Are there any hand-written, untracked `migrate_*.py` scripts still
      sitting alongside `alembic/` (per V2/V3's noted pattern of these
      accumulating)? If so, list them — they don't need to be removed
      immediately, but they should be named so they don't silently keep
      growing.

**Once confirmed either way:** update `NEXOPS_MASTER_STATUS_V4.md`
Section 4 to change "likely resolved" to either "confirmed resolved" or
the real current state, with whatever you found as the evidence.

---

## 2. Delete the 3 stale PagerDuty webhook subscriptions

**Why:** Flagged since `NEXOPS_MASTER_STATUS_V2.md` — encrypted with an
old key, undecryptable, pointing at users that may no longer resolve
correctly. Only one current subscription (`PQU3XPH`) is valid.

**Action, directly in PagerDuty's dashboard (Integrations → Webhooks or
Extensions, depending on your PagerDuty plan/UI):**
- [ ] Delete `PK97OMG`
- [ ] Delete `PLB73G6`
- [ ] Delete `PXD0N8O`
- [ ] Confirm `PQU3XPH` is still present and still the one actively
      receiving events (spot-check: trigger a test event, confirm it's
      received)

**Once done:** update `NEXOPS_MASTER_STATUS_V4.md` Section 4 to move this
line from "carried forward, open" to closed, with the date it was done.

---

## 3. Keep Neon compute warm before onboarding real teams

**Why:** the pre-launch smoke test found a real cold-start gap (Neon
serverless compute resuming from idle took ~25-45s in testing). A real
GitHub/PagerDuty webhook hitting a cold database risks the provider's own
delivery timeout — the same class of problem that caused the duplicate-
incident bug fixed earlier in this project (`NEXOPS_MASTER_STATUS_V2.md`).

- [ ] Check Neon's project settings for compute auto-suspend / scale-to-
      zero behavior on the production branch.
- [ ] Either disable auto-suspend or extend the idle timeout well beyond
      realistic gaps between real webhook traffic, depending on cost
      tradeoffs you're comfortable with.
- [ ] Confirm the change with a quick real test: leave the app idle past
      the old suspend threshold, send a real webhook, confirm no
      multi-second cold-start delay.

## 4. Add Redis keepalive settings

**Why:** the same smoke test found the Redis Streams worker losing its
connection during idle periods (Redis Cloud dropping idle TCP sockets),
causing reconnect/retry cycles before it picks up new events.

- [ ] Add `health_check_interval` and TCP keepalive settings to the Redis
      client configuration in the worker (`app/worker/stream_consumer.py`
      per the smoke test follow-up report).
- [ ] Confirm with a quick real test: leave the worker idle for a few
      minutes, trigger a real event, confirm pickup latency is
      consistently low rather than showing the multi-second reconnect
      pattern.

---

## 5. Decide on Automation/Clusters/CI/CD/Topology sidebar sections

**Status: open, deliberately deferred — your call.**

These are real, fully-built features, not stubs, and they directly
contradict the narrow-scope positioning
`NEXOPS_BUSINESS_GTM_FOUNDATION.md` is built on (Section 8: "the
sharpest available positioning is narrow, not broad"). No action taken
yet — flagged here so it doesn't get lost before outreach starts. When
ready, the options are: hide them (nav + routes) to keep the narrow
pitch consistent, or keep them and drop/adjust the narrow-scope framing
in outreach messaging.

---

## After all items are done

Both remaining items in this checklist are the last things standing
between the current state and treating the technical/verification side of
this project as genuinely current. Once checked off:

- Re-verify `NEXOPS_MASTER_STATUS_V4.md` against the live system one more
  time (its own standing rule).
- Move to `NEXOPS_BUSINESS_GTM_FOUNDATION.md`'s next step: get the
  Starter tier in front of 5–10 real teams and watch real confirm/reject
  usage before setting a price or building billing.
