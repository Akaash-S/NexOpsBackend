#!/usr/bin/env python3
"""
NexOps Post-Deploy Health & Smoke Verification Script.

Usage:
  export BASE_URL="https://nexops-server.asolvitra.tech"  # or http://localhost:8000
  export HEALTH_CHECK_SECRET="your-secret-here"
  python scripts/post_deploy_smoke.py

Verifies:
  1. Public /health returns HTTP 200 and status == "operational"
  2. Protected /health/detailed authenticated via HEALTH_CHECK_SECRET returns HTTP 200
  3. Diagnostic queries succeed:
     - database_connection
     - database_events_query (created_at >= now-7d)
     - database_alerts_query (created_at >= now-7d)
     - database_alembic_revision
     - redis_ping
     - package_versions (compares installed versions against pinned requirements.txt)
  4. Prints installed versions and exits non-zero on any check failure or version mismatch.
"""

import os
import sys
import argparse
import urllib.request
import urllib.error
import json
import time


def run_smoke_check(base_url: str) -> bool:
    secret = os.getenv("HEALTH_CHECK_SECRET", "").strip()
    base_url = base_url.rstrip("/")
    print("=" * 70)
    print(" NexOps Post-Deploy Smoke Check")
    print(f" Target Base URL: {base_url}")
    print(f" HEALTH_CHECK_SECRET: {'Configured in environment' if secret else 'NOT SET in environment (Warning: detailed check will fail 401)'}")
    print("=" * 70)

    all_passed = True

    # 1. Check Public /health
    public_url = f"{base_url}/health"
    print(f"\n[1/2] Checking Public Health Endpoint: {public_url}")
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(public_url, headers={"User-Agent": "NexOps-SmokeTest/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            code = resp.getcode()
            body = resp.read().decode("utf-8")
            data = json.loads(body)
            status_val = data.get("status")
            if code == 200 and status_val == "operational":
                print(f"  --> PASS | HTTP {code} in {elapsed}ms | status: '{status_val}', service: '{data.get('service')}'")
            else:
                print(f"  --> FAIL | HTTP {code} in {elapsed}ms | unexpected body: {data}")
                all_passed = False
    except urllib.error.HTTPError as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        print(f"  --> FAIL | HTTP {e.code} in {elapsed}ms: {e.read().decode('utf-8', errors='replace')}")
        all_passed = False
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        print(f"  --> FAIL | Network / Connection Error in {elapsed}ms: {e}")
        all_passed = False

    # 2. Check Protected /health/detailed
    detailed_url = f"{base_url}/health/detailed"
    print(f"\n[2/2] Checking Protected Detailed Health Endpoint: {detailed_url}")
    t0 = time.perf_counter()
    headers = {
        "User-Agent": "NexOps-SmokeTest/1.0",
        "Accept": "application/json",
    }
    if secret:
        headers["X-Health-Check-Secret"] = secret

    detailed_data = None
    detailed_code = 0
    try:
        req = urllib.request.Request(detailed_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            detailed_code = resp.getcode()
            detailed_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        detailed_code = e.code
        try:
            detailed_data = json.loads(e.read().decode("utf-8"))
        except Exception:
            detailed_data = {"error": str(e)}
    except Exception as e:
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        print(f"  --> FAIL | Detailed check connection error in {elapsed}ms: {e}")
        return False

    if detailed_code != 200:
        print(f"  --> FAIL | HTTP {detailed_code} returned (Expected 200 OK)")
        all_passed = False
    else:
        print(f"  --> HTTP {detailed_code} in {elapsed}ms | Top-level status: '{detailed_data.get('status')}'")

    # 3. Print Installed Package Versions & Check for Mismatches
    checks = detailed_data.get("checks", {})
    if not checks:
        if detailed_code == 401:
            print("\n  [!] auth failed (HTTP 401), versions not available")
        else:
            print(f"\n  [!] Response has no 'checks' object (HTTP {detailed_code}), versions not available.")
        all_passed = False
    else:
        pkg_check = checks.get("package_versions", {})
        installed_versions = detailed_data.get("package_versions") or pkg_check.get("installed", {})
        expected_versions = pkg_check.get("expected", {})
        mismatches = pkg_check.get("mismatches", [])

        print("\nInstalled Package Versions (vs pinned requirements.txt):")
        print(f"  {'PACKAGE':<15} | {'INSTALLED':<12} | {'EXPECTED PINNED':<15} | {'STATUS'}")
        print("  " + "-" * 55)
        for pkg in ["sqlmodel", "sqlalchemy", "asyncpg", "pydantic", "fastapi"]:
            inst = installed_versions.get(pkg, "unknown")
            exp = expected_versions.get(pkg, "unknown")
            status_str = "MATCH" if (inst == exp and inst != "unknown") else "MISMATCH"
            print(f"  {pkg:<15} | {str(inst):<12} | {str(exp):<15} | {status_str}")

        if pkg_check.get("status") != "pass" or mismatches:
            print(f"\n  [!] VERSION MISMATCH DETECTED: {mismatches}")
            all_passed = False

        # 4. Inspect individual diagnostic checks
        print("\nIndividual Diagnostic Checks:")
        print(f"  {'CHECK NAME':<30} | {'STATUS':<6} | {'DETAILS'}")
        print("  " + "-" * 65)

        for check_name, info in checks.items():
            c_status = info.get("status", "unknown").upper()
            details = []
            if "latency_ms" in info:
                details.append(f"{info['latency_ms']}ms")
            if "count" in info:
                details.append(f"count={info['count']}")
            if "revision" in info:
                details.append(f"rev={info['revision']}")
            if "error" in info and info["error"]:
                details.append(f"error: {info['error']}")
            if "mismatches" in info and info["mismatches"]:
                details.append(f"mismatches: {info['mismatches']}")

            detail_str = ", ".join(details)
            print(f"  {check_name:<30} | {c_status:<6} | {detail_str}")

            if c_status != "PASS":
                all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print(" [ALL CHECKS PASSED] System is operational, healthy, and regression-free.")
        print("=" * 70)
        return True
    else:
        print(" [DEPLOYMENT SMOKE CHECK FAILED] One or more health checks or version checks failed!")
        print("=" * 70)
        return False


def main():
    parser = argparse.ArgumentParser(description="NexOps Post-Deploy Smoke Verification")
    parser.add_argument(
        "--base-url",
        default=os.getenv("BASE_URL", "https://nexops-server.asolvitra.tech"),
        help="Base URL of NexOps API (e.g. https://nexops-server.asolvitra.tech or http://localhost:8000)"
    )
    args = parser.parse_args()

    success = run_smoke_check(args.base_url)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
