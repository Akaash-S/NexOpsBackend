# NexOps — URGENT: Disable `/api/v1/execute` in Production

> **STATUS:** COMPLETED (July 24, 2026)  
> **Report:** [NEXOPS_URGENT_DISABLE_EXECUTOR_REPORT.md](file:///d:/Projects/ReactJS/NexOps/docs/NEXOPS_URGENT_DISABLE_EXECUTOR_REPORT.md)  
> **Live Production Response:** `HTTP 404 Not Found` (`{"detail":"Not Found"}`)  
> **Backend Commit:** `5b17bf1320955e741b204aa3e19f34183cbcfa34`

Use this as the task brief for the coding agent. **This is time-sensitive
and takes priority over everything else, including landing page work.**
`/api/v1/execute` accepts arbitrary Python/Node.js code from an
authenticated user and runs it on the live backend, with no verified
network isolation, filesystem restriction, or resource limits beyond a
5-second timer. Real teams may be onboarded soon. This needs to not be
reachable in production until it's either properly secured or
deliberately removed.

---

## Ground rules

Same standing discipline as every prior pass: real evidence, no claim
without it. Given the stakes here, err toward the more cautious action
if anything is ambiguous.

---

## Part 1 — Take it offline now

- Disable `/api/v1/execute` in production immediately — whichever is
  fastest and most reliable: a feature flag, removing the route from
  `main.py`'s mounted routers, or an infra-level block. State exactly
  which method was used.
- Confirm it's actually down: a real request to the live production URL
  now returns 404 or 403, not 200.
- Confirm this doesn't break anything else that depends on it — search
  the codebase for any internal caller of this route (frontend or
  backend) and confirm none exist, or note what does and how it's
  affected.

## Part 2 — Real security assessment (not another "safe code" test)

Answer these directly, with real evidence, not inference:

1. **Network isolation:** from inside a submitted code execution, can
   outbound network requests be made? Specifically, can the code reach
   the cloud provider's metadata endpoint (`169.254.169.254`) or any
   other internal/external address? Test this for real if it's safe to
   do so in a non-production context; if not safe to test at all, say so
   and treat it as unverified-and-therefore-unsafe.
2. **Filesystem isolation:** can submitted code read files outside its
   intended temp directory — application source, other repos' data, any
   file on the host?
3. **Resource limits:** is there an actual memory/CPU limit, or only the
   5-second wall-clock timeout? What happens with a deliberately
   resource-heavy submission (within a safe, bounded test)?
4. **Container/process isolation:** does this run in an isolated
   container (Docker with no network, gVisor, etc.) or as a bare
   subprocess on the same host as the rest of the application?
5. **Origin:** why does this endpoint exist? Check commit history/PR
   context around its creation (`130edd4e`) and hardening (`a1fb314a`) for
   any stated purpose. Is it tied to any actual product feature, or was
   it a development/debugging tool that ended up mounted in the public
   API by mistake?

## Part 3 — Recommendation, not a decision

Do not re-enable this endpoint as part of this task. Based on Part 2's
findings, give a clear recommendation:
- If it has no real product purpose: recommend permanent removal.
- If it has a real purpose but isn't properly isolated: state exactly
  what would be required (real container isolation, network egress
  blocking, resource limits) before it could safely be reintroduced.
- If it's already properly isolated and Part 2 didn't find real gaps:
  say so plainly with the evidence — but the default posture until proven
  otherwise is "keep it offline."

---

## Output format

Short, urgent report. Part 1 confirmation first (is it actually down,
right now, with a real request proving it). Part 2 findings. Part 3
recommendation. End with:

> Is `/api/v1/execute` confirmed offline in production right now, and is
> there a clear, evidence-based recommendation for whether/how it should
> ever come back?
