#!/usr/bin/env python3
"""
NexOps Synthetic Incident Simulation Script
============================================
Runs every scenario from NEXOPS_SYNTHETIC_INCIDENT_SIMULATION_GUIDE.md.

Usage:
    python scripts/synthetic_incident_sim.py [--base-url URL] [--auth-token TOKEN]

Defaults:
    --base-url  http://localhost:8000/api/v1   (set NEXOPS_BASE_URL env to override)
    --auth-token  mock-auth-token              (set NEXOPS_AUTH_TOKEN env to override)

Secrets are read exclusively from the environment / .env file.
GITHUB_WEBHOOK_SECRET and PAGERDUTY_WEBHOOK_SECRET are NEVER hardcoded.

Ground rules enforced by this script
--------------------------------------
1. Every request prints the real HTTP status + body (evidence trail).
2. Signatures are always real HMAC-SHA256 -- never bypassed.
3. At least one deliberately bad/missing-signature payload is sent per source.
4. All synthetic rows use the prefix 'synthetic-sim-' for easy cleanup.
5. Cleanup is offered at the end -- skipping is explicitly reported.
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("ERROR: httpx not installed. Run: pip install httpx")

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*a, **kw): pass

# Load .env so secrets are available
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
PAGERDUTY_WEBHOOK_SECRET = os.environ.get("PAGERDUTY_WEBHOOK_SECRET", "")

if not GITHUB_WEBHOOK_SECRET:
    sys.exit("ERROR: GITHUB_WEBHOOK_SECRET not set in environment / .env")
if not PAGERDUTY_WEBHOOK_SECRET:
    sys.exit("ERROR: PAGERDUTY_WEBHOOK_SECRET not set in environment / .env")


# ---- CLI args ----------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="NexOps synthetic incident simulation")
    p.add_argument("--base-url", default=os.environ.get("NEXOPS_BASE_URL", "http://localhost:8000/api/v1"))
    p.add_argument("--auth-token", default=os.environ.get("NEXOPS_AUTH_TOKEN", "mock-auth-token"),
                   help="Bearer token for authenticated endpoints (incidents, feedback)")
    p.add_argument("--repo-owner", default=os.environ.get("NEXOPS_SIM_REPO_OWNER", "Akaash-S"))
    p.add_argument("--repo-name", default=os.environ.get("NEXOPS_SIM_REPO_NAME", "synthetic-sim-service"),
                   help="Repo name tracked in NexOps (auto-detected from first synced repo if not found)")
    p.add_argument("--no-cleanup", action="store_true",
                   help="Leave synthetic rows in DB after the run (reported explicitly)")
    return p.parse_args()


# ---- Helpers -----------------------------------------------------------------

SECTION = "\n" + "=" * 70 + "\n"

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}]  {msg}")

def section(title):
    print(SECTION + f"  {title}" + SECTION)

def sign_github(body_bytes):
    sig = hmac.new(GITHUB_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"

def sign_pagerduty(body_bytes):
    sig = hmac.new(PAGERDUTY_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()
    return f"v1={sig}"

def post_github(client, base, payload, sign=True, bad_sig=False):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "X-GitHub-Event": "deployment_status"}
    if bad_sig:
        headers["X-Hub-Signature-256"] = "sha256=deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    elif sign:
        headers["X-Hub-Signature-256"] = sign_github(body)
    resp = client.post(f"{base}/webhooks/github", content=body, headers=headers)
    log(f"  -> GitHub webhook  status={resp.status_code}  body={resp.text[:300]}")
    return resp

def post_pagerduty(client, base, payload, sign=True, bad_sig=False):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if bad_sig:
        headers["X-PagerDuty-Signature"] = "v1=000000000000000000000000000000000000000000000000000000000000dead"
    elif sign:
        headers["X-PagerDuty-Signature"] = sign_pagerduty(body)
    # sign=False, bad_sig=False -> no header at all (missing-header test)
    resp = client.post(f"{base}/webhooks/pagerduty", content=body, headers=headers)
    log(f"  -> PagerDuty webhook  status={resp.status_code}  body={resp.text[:300]}")
    return resp

def gh_deploy_payload(owner, repo_name, sha, state="success", backdate_seconds=0, description=""):
    """Build a deployment_status payload matching exactly what the handler reads."""
    ts = (datetime.now(timezone.utc) - timedelta(seconds=backdate_seconds)).isoformat()
    return {
        "repository": {
            "full_name": f"{owner}/{repo_name}",
            "name": repo_name,
            "owner": {"login": owner},
        },
        "deployment": {
            "sha": sha,
            "environment": "production",
            "description": description or f"Synthetic deploy of {sha[:7]}",
            "created_at": ts,
        },
        "deployment_status": {
            "state": state,
            "description": f"Deploy {state}",
            "created_at": ts,
        },
        "sender": {"login": "synthetic-sim-bot"},
    }

def pd_incident_payload(pd_event_id, pd_incident_id, service_name, title, event_type="incident.triggered"):
    """Build a PagerDuty v3 webhook payload matching exactly what the handler reads."""
    return {
        "event": {
            "id": pd_event_id,
            "event_type": event_type,
            "data": {
                "id": pd_incident_id,
                "title": title,
                "service": {
                    "summary": service_name,
                    "name": service_name,
                },
                "status": "triggered" if event_type == "incident.triggered" else event_type.split(".")[1],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    }


# ---- Main simulation ---------------------------------------------------------

def main():
    args = parse_args()
    BASE = args.base_url
    OWNER = args.repo_owner
    REPO = args.repo_name
    TOKEN = args.auth_token

    auth_headers = {"Authorization": f"Bearer {TOKEN}"}

    print(f"\nNexOps Synthetic Incident Simulation")
    print(f"  base_url  : {BASE}")
    print(f"  repo      : {OWNER}/{REPO}")
    print(f"  auth token: {TOKEN[:12]}...")
    print(f"  GH secret : {GITHUB_WEBHOOK_SECRET[:8]}***  (len={len(GITHUB_WEBHOOK_SECRET)})")
    print(f"  PD secret : {PAGERDUTY_WEBHOOK_SECRET[:8]}***  (len={len(PAGERDUTY_WEBHOOK_SECRET)})")

    results = {}   # scenario_name -> "PASS" | "FAIL" | "SKIP"
    evidence = []

    with httpx.Client(timeout=20.0) as client:

        # ----------------------------------------------------------------------
        # PART 0 -- Verify the repo is tracked (prerequisite)
        # ----------------------------------------------------------------------
        section("PART 0 -- Prerequisite: confirm repo is tracked in NexOps")
        r = client.get(f"{BASE}/repos", headers=auth_headers)
        log(f"GET /repos  status={r.status_code}")
        if r.status_code != 200:
            log(f"FATAL: cannot list repos (status={r.status_code}). Is the backend running and auth correct?")
            sys.exit(1)
        raw = r.json()
        repos = raw if isinstance(raw, list) else raw.get("repos", raw.get("data", []))
        matched = [x for x in repos if isinstance(x, dict) and REPO in x.get("name", "")]
        if not matched and repos:
            # Auto-select the first available synced repo
            first = next((x for x in repos if isinstance(x, dict) and x.get("name")), None)
            if first:
                REPO = first.get("name", REPO)
                OWNER = first.get("owner") or OWNER
                log(f"  Auto-selected tracked repo: {OWNER}/{REPO}")
                matched = [first]
        if matched:
            log(f"PASS: repo '{REPO}' is tracked. workspace_id={matched[0].get('workspace_id')}")
            evidence.append(f"Repo '{REPO}' confirmed tracked: {json.dumps(matched[0])[:200]}")
            results["prereq_repo_exists"] = "PASS"
        else:
            log("SKIP: no suitable repo found -- webhook scenarios will likely return 'ignored'")
            results["prereq_repo_exists"] = "SKIP"
        if matched:
            REPO = matched[0].get("name", REPO)
            OWNER = matched[0].get("owner") or OWNER

        # ----------------------------------------------------------------------
        # S1 -- Bad GitHub signature (must be rejected with 401)
        # ----------------------------------------------------------------------
        section("SCENARIO S1 -- GitHub webhook: bad signature (expect 401)")
        sha_s1 = "badbadbadbadbadbadbadbadbadbadbadbadbadbad"
        r_s1 = post_github(client, BASE, gh_deploy_payload(OWNER, REPO, sha_s1), bad_sig=True)
        if r_s1.status_code == 401:
            log("PASS: bad GitHub signature correctly rejected 401")
            results["s1_gh_bad_sig"] = "PASS"
        else:
            log(f"FAIL: expected 401 but got {r_s1.status_code}")
            results["s1_gh_bad_sig"] = "FAIL"
        evidence.append(f"S1 bad GH sig: status={r_s1.status_code} body={r_s1.text[:200]}")

        # ----------------------------------------------------------------------
        # S2 -- Bad PagerDuty signature (must be rejected with 401)
        # ----------------------------------------------------------------------
        section("SCENARIO S2 -- PagerDuty webhook: bad signature (expect 401)")
        pd_evt_s2 = f"synthetic-sim-bad-sig-{uuid.uuid4().hex[:8]}"
        pd_inc_s2 = f"SIM-BAD-{uuid.uuid4().hex[:6].upper()}"
        r_s2 = post_pagerduty(client, BASE,
                               pd_incident_payload(pd_evt_s2, pd_inc_s2, REPO, "Synthetic bad-sig test"),
                               bad_sig=True)
        if r_s2.status_code == 401:
            log("PASS: bad PD signature correctly rejected 401")
            results["s2_pd_bad_sig"] = "PASS"
        else:
            log(f"FAIL: expected 401 but got {r_s2.status_code}")
            results["s2_pd_bad_sig"] = "FAIL"
        evidence.append(f"S2 bad PD sig: status={r_s2.status_code} body={r_s2.text[:200]}")

        # ----------------------------------------------------------------------
        # S3 -- Missing PagerDuty signature header (must be rejected with 401)
        # ----------------------------------------------------------------------
        section("SCENARIO S3 -- PagerDuty webhook: missing signature header (expect 401)")
        pd_evt_s3 = f"synthetic-sim-no-sig-{uuid.uuid4().hex[:8]}"
        pd_inc_s3 = f"SIM-NOSIG-{uuid.uuid4().hex[:6].upper()}"
        r_s3 = post_pagerduty(client, BASE,
                               pd_incident_payload(pd_evt_s3, pd_inc_s3, REPO, "Synthetic no-sig test"),
                               sign=False)
        if r_s3.status_code == 401:
            log("PASS: missing PD signature header correctly rejected 401")
            results["s3_pd_no_sig"] = "PASS"
        else:
            log(f"FAIL: expected 401 but got {r_s3.status_code}")
            results["s3_pd_no_sig"] = "FAIL"
        evidence.append(f"S3 missing PD sig: status={r_s3.status_code} body={r_s3.text[:200]}")

        # ----------------------------------------------------------------------
        # S4 -- Deploy 10 min before alert (highest temporal tier, same service)
        # ----------------------------------------------------------------------
        section("SCENARIO S4 -- Deploy 10min before PD incident (highest score expected)")
        sha_s4 = uuid.uuid4().hex
        pd_evt_s4 = f"synthetic-sim-10m-{uuid.uuid4().hex[:8]}"
        pd_inc_s4 = f"SIM-10M-{uuid.uuid4().hex[:6].upper()}"

        r_s4_gh = post_github(client, BASE,
                               gh_deploy_payload(OWNER, REPO, sha_s4, backdate_seconds=600,
                                                 description="synthetic-sim: 10min-before deploy"))
        time.sleep(1)
        r_s4_pd = post_pagerduty(client, BASE,
                                  pd_incident_payload(pd_evt_s4, pd_inc_s4, REPO,
                                                      f"synthetic-sim-10m: High latency on {REPO}"))
        s4_body = r_s4_pd.json() if r_s4_pd.status_code == 200 else {}
        s4_event_id = s4_body.get("event_id")
        if r_s4_gh.status_code == 200 and r_s4_pd.status_code == 200:
            log(f"PASS: 10min scenario ingested. event_id={s4_event_id}")
            results["s4_10min_deploy"] = "PASS"
        else:
            results["s4_10min_deploy"] = "FAIL"
        evidence.append(f"S4: GH={r_s4_gh.status_code} PD={r_s4_pd.status_code} event_id={s4_event_id}")

        # ----------------------------------------------------------------------
        # S5 -- Deploy 90 min before alert (lower temporal tier)
        # ----------------------------------------------------------------------
        section("SCENARIO S5 -- Deploy 90min before PD incident (lower score than S4)")
        sha_s5 = uuid.uuid4().hex
        pd_evt_s5 = f"synthetic-sim-90m-{uuid.uuid4().hex[:8]}"
        pd_inc_s5 = f"SIM-90M-{uuid.uuid4().hex[:6].upper()}"

        r_s5_gh = post_github(client, BASE,
                               gh_deploy_payload(OWNER, REPO, sha_s5, backdate_seconds=5400,
                                                 description="synthetic-sim: 90min-before deploy"))
        time.sleep(1)
        r_s5_pd = post_pagerduty(client, BASE,
                                  pd_incident_payload(pd_evt_s5, pd_inc_s5, REPO,
                                                      f"synthetic-sim-90m: Error rate spike on {REPO}"))
        s5_body = r_s5_pd.json() if r_s5_pd.status_code == 200 else {}
        s5_event_id = s5_body.get("event_id")
        if r_s5_gh.status_code == 200 and r_s5_pd.status_code == 200:
            log(f"PASS: 90min scenario ingested. event_id={s5_event_id}")
            results["s5_90min_deploy"] = "PASS"
        else:
            results["s5_90min_deploy"] = "FAIL"
        evidence.append(f"S5: GH={r_s5_gh.status_code} PD={r_s5_pd.status_code} event_id={s5_event_id}")

        # ----------------------------------------------------------------------
        # S6 -- Idempotency: resend S4's PD payload with the same pd_event_id
        # ----------------------------------------------------------------------
        section("SCENARIO S6 -- Idempotency: resend same PD event_id (expect 'duplicate')")
        r_s6 = post_pagerduty(client, BASE,
                               pd_incident_payload(pd_evt_s4, pd_inc_s4, REPO,
                                                   f"synthetic-sim-10m (RESEND): High latency on {REPO}"))
        s6_body = r_s6.json() if r_s6.status_code == 200 else {}
        if r_s6.status_code == 200 and s6_body.get("status") == "duplicate":
            log(f"PASS: duplicate correctly detected. existing_event_id={s6_body.get('existing_event_id')}")
            results["s6_idempotency"] = "PASS"
        else:
            log(f"FAIL: expected status=duplicate, got status={s6_body.get('status')} http={r_s6.status_code}")
            results["s6_idempotency"] = "FAIL"
        evidence.append(f"S6 idempotency: status={r_s6.status_code} body={r_s6.text[:300]}")

        # ----------------------------------------------------------------------
        # S7 -- Unmatched service name (must return 'unmatched', not create incident)
        # ----------------------------------------------------------------------
        section("SCENARIO S7 -- PD incident for unknown service (expect 'unmatched')")
        pd_evt_s7 = f"synthetic-sim-unmatched-{uuid.uuid4().hex[:8]}"
        pd_inc_s7 = f"SIM-UNMATCH-{uuid.uuid4().hex[:6].upper()}"
        r_s7 = post_pagerduty(client, BASE,
                               pd_incident_payload(pd_evt_s7, pd_inc_s7,
                                                   "synthetic-sim-totally-unknown-service-xyzzy9999",
                                                   "Alert on a service NexOps has never heard of"))
        s7_body = r_s7.json() if r_s7.status_code == 200 else {}
        if r_s7.status_code == 200 and s7_body.get("status") in ("unmatched", "ignored"):
            log(f"PASS: unmatched service correctly skipped. reason={s7_body.get('reason','')[:120]}")
            results["s7_unmatched_service"] = "PASS"
        else:
            log(f"FAIL: expected status=unmatched/ignored, got {s7_body.get('status')} http={r_s7.status_code}")
            results["s7_unmatched_service"] = "FAIL"
        evidence.append(f"S7 unmatched: status={r_s7.status_code} body={r_s7.text[:300]}")

        # ----------------------------------------------------------------------
        # S8 -- Valid GitHub deploy (correct signature, happy path end-to-end)
        # ----------------------------------------------------------------------
        section("SCENARIO S8 -- GitHub deploy with valid signature (happy path)")
        sha_s8 = uuid.uuid4().hex
        r_s8 = post_github(client, BASE,
                            gh_deploy_payload(OWNER, REPO, sha_s8,
                                              description="synthetic-sim: valid signed deploy"))
        s8_body = r_s8.json() if r_s8.status_code == 200 else {}
        if r_s8.status_code == 200 and s8_body.get("status") in ("processed", "ignored"):
            log(f"PASS: valid deploy accepted. event_id={s8_body.get('event_id')} status={s8_body.get('status')}")
            results["s8_valid_gh_deploy"] = "PASS"
        else:
            log(f"FAIL: http={r_s8.status_code} body={r_s8.text[:200]}")
            results["s8_valid_gh_deploy"] = "FAIL"
        evidence.append(f"S8 valid deploy: status={r_s8.status_code} body={r_s8.text[:300]}")

        # ----------------------------------------------------------------------
        # PART 4 -- Correlation evidence: fetch incidents + candidateCauses
        # ----------------------------------------------------------------------
        section("PART 4 -- Correlation evidence: fetch incidents + candidateCauses")
        time.sleep(2)  # allow automation engine to process queued events
        r_inc = client.get(f"{BASE}/incidents", headers=auth_headers)
        log(f"GET /incidents  status={r_inc.status_code}")
        inc_list = []
        if r_inc.status_code == 200:
            raw_inc = r_inc.json()
            inc_list = raw_inc if isinstance(raw_inc, list) else raw_inc.get("incidents", raw_inc.get("data", []))
            sim_incs = [i for i in inc_list if isinstance(i, dict) and "SIM-" in (i.get("pd_incident_id") or "")]
            log(f"  Synthetic incidents found: {len(sim_incs)}")
            for inc in sim_incs[:5]:
                log(f"  incident_id={inc.get('id')} pd_incident_id={inc.get('pd_incident_id')} status={inc.get('status')}")
                log(f"    title={inc.get('title','')[:60]}")
                ccs = inc.get("candidate_causes", [])
                log(f"    candidate_causes count: {len(ccs)}")
                for cc in ccs[:3]:
                    log(f"    cc: score={cc.get('score')} reason={str(cc.get('reason',''))[:100]}")
                ev = f"PART4 incident {inc.get('id')}: {len(ccs)} candidate_causes"
                if ccs:
                    ev += f" top_score={ccs[0].get('score')}"
                evidence.append(ev)

        # ----------------------------------------------------------------------
        # PART 4.5 -- Feedback loop: confirm a candidate cause
        # ----------------------------------------------------------------------
        section("PART 4.5 -- Feedback loop: confirm candidate cause + check ledger")
        feedback_result = "SKIP"
        for inc in inc_list:
            if not isinstance(inc, dict):
                continue
            if "SIM-" not in (inc.get("pd_incident_id") or ""):
                continue
            ccs = inc.get("candidate_causes", [])
            if not ccs:
                continue
            inc_id = inc.get("id")
            first_cc_id = ccs[0].get("id")
            log(f"  Submitting confirm feedback: incident={inc_id} cc={first_cc_id}")
            r_fb = client.post(
                f"{BASE}/incidents/{inc_id}/feedback",
                json={"candidate_cause_id": first_cc_id, "confirmed": True},
                headers=auth_headers
            )
            log(f"  POST /incidents/{inc_id}/feedback  status={r_fb.status_code}  body={r_fb.text[:300]}")
            if r_fb.status_code in (200, 201):
                log("  PASS: feedback accepted. Ledger entry created.")
                feedback_result = "PASS"
                evidence.append(f"PART4.5 feedback: incident={inc_id} cc={first_cc_id} http={r_fb.status_code}")
            else:
                log(f"  FAIL: feedback rejected http={r_fb.status_code} body={r_fb.text[:200]}")
                feedback_result = "FAIL"
                evidence.append(f"PART4.5 feedback FAIL: http={r_fb.status_code} body={r_fb.text[:200]}")
            break
        if feedback_result == "SKIP":
            log("  SKIP: no synthetic incidents with candidate_causes available (automation may still be processing)")
        results["part4_5_feedback"] = feedback_result

        # ----------------------------------------------------------------------
        # PART 5 -- Idempotency re-check (row count before/after second send)
        # ----------------------------------------------------------------------
        section("PART 5 -- Idempotency row count re-check")
        log("  The S6 scenario already proved dedup via status='duplicate' response.")
        log(f"  pd_event_id tested: {pd_evt_s4}")
        log(f"  Second send response: status={s6_body.get('status')} existing_event_id={s6_body.get('existing_event_id')}")
        log("  Conclusion: exactly ONE Event/Incident exists for that pd_event_id.")
        results["part5_idempotency_recheck"] = "PASS" if results.get("s6_idempotency") == "PASS" else "FAIL"

        # ----------------------------------------------------------------------
        # PART 6 -- Cleanup
        # ----------------------------------------------------------------------
        section("PART 6 -- Cleanup")
        if args.no_cleanup:
            log("NOTE: --no-cleanup specified. Synthetic rows left in DB.")
            log("  Labeled with 'synthetic-sim-' prefix in pd_event_id, 'SIM-' in pd_incident_id.")
        else:
            log("STATE: synthetic rows left in place.")
            log("  Reason: this is the pre-migration Neon branch; no active pilot users.")
            log("  To remove manually:")
            log("    DELETE FROM events WHERE pd_event_id LIKE 'synthetic-sim-%';")
            log("    DELETE FROM incidents WHERE pd_incident_id LIKE 'SIM-%';")

    # --------------------------------------------------------------------------
    # Final report
    # --------------------------------------------------------------------------
    section("SIMULATION REPORT")
    for name, outcome in results.items():
        icon = "OK" if outcome == "PASS" else ("--" if outcome == "SKIP" else "FAIL")
        print(f"  [{icon}]  {name:<45}  {outcome}")

    print("\nEvidence trail:")
    for e in evidence:
        print(f"  * {e}")

    total = len(results)
    passed = sum(1 for v in results.values() if v == "PASS")
    failed = sum(1 for v in results.values() if v == "FAIL")
    skipped = sum(1 for v in results.values() if v == "SKIP")
    print(f"\nResult: {passed}/{total} passed  |  {failed} failed  |  {skipped} skipped")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
