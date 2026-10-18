"""
NexOps Load Benchmark: Webhook Ingestion & Worker Throughput
Benchmark Environment: local, single machine (Windows Laptop)
NOTE: All numbers recorded in this benchmark reflect a single local Windows machine
running local PostgreSQL and Redis instances. They must NOT be quoted as production figures.
"""

import asyncio
import os
import sys
import time
import uuid
import platform
import statistics
import hmac
import hashlib
import json
from typing import List, Dict, Any
from datetime import datetime, timezone
import httpx
from sqlalchemy import text
from sqlmodel import select

# Setup root path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.main import app
from app.core.config import settings
from app.core.database import async_session
from app.core.redis import init_redis, redis_client
from app.core.rate_limit import limiter
from app.models.workspace import Workspace
from app.models.user import User
from app.models.repo import Repo
from app.models.event import Event
from app.api.routes.integrations import _make_pd_uid_token
from app.worker.stream_consumer import handle_message, init_consumer_group, STREAM_NAME, GROUP_NAME


def verify_localhost_target(target_url: str = None):
    """
    Ensure load tests execute exclusively against local development environments.
    Strictly refuses execution if DATABASE_URL, REDIS_URL, or TARGET_URL points to a remote host.
    """
    from urllib.parse import urlparse

    # 1. Check Target URL if provided via argument or environment
    candidate_target = target_url or os.getenv("TARGET_URL") or os.getenv("BASE_URL")
    if candidate_target:
        parsed = urlparse(candidate_target)
        host = parsed.hostname or ""
        if host not in ("localhost", "127.0.0.1", "::1"):
            print(f"\n[CRITICAL SAFETY REFUSAL] Target host '{host}' is NOT localhost!")
            print("Load tests are strictly prohibited from targeting remote, staging, or production environments.")
            raise RuntimeError(f"SAFETY REFUSAL: Target host '{host}' is non-local.")

    # 2. Check Database URL host
    db_parsed = urlparse(settings.DATABASE_URL)
    db_host = db_parsed.hostname or ""
    if db_host not in ("localhost", "127.0.0.1", "::1"):
        print(f"\n[CRITICAL SAFETY REFUSAL] DATABASE_URL host '{db_host}' is NOT localhost!")
        raise RuntimeError(f"SAFETY REFUSAL: DATABASE_URL host '{db_host}' is non-local.")

    # 3. Check Redis URL host
    redis_parsed = urlparse(settings.REDIS_URL)
    redis_host = redis_parsed.hostname or ""
    if redis_host not in ("localhost", "127.0.0.1", "::1"):
        print(f"\n[CRITICAL SAFETY REFUSAL] REDIS_URL host '{redis_host}' is NOT localhost!")
        raise RuntimeError(f"SAFETY REFUSAL: REDIS_URL host '{redis_host}' is non-local.")


def get_machine_specs() -> Dict[str, str]:
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "processor": platform.processor() or "Unknown",
        "cpu_count": str(os.cpu_count() or "Unknown"),
        "python_version": platform.python_version(),
        "database": f"PostgreSQL (local, port 5432, {settings.DATABASE_URL.split('@')[-1] if '@' in settings.DATABASE_URL else 'local'})",
        "redis": f"Redis (local, {settings.REDIS_URL})",
        "classification": "local, single machine (Windows laptop with local Postgres and Redis)",
    }


async def setup_test_entities():
    """Create test workspace, user, and repository for load testing."""
    test_id = uuid.uuid4().hex[:8]
    ws_id = f"ws-load-{test_id}"
    user_id = f"usr-load-{test_id}"
    repo_id = f"repo-load-{test_id}"

    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))

        workspace = Workspace(
            id=ws_id,
            name=f"Load Test Workspace {test_id}",
            scoring_strategy="balanced",
        )
        session.add(workspace)
        await session.flush()

        user = User(
            id=user_id,
            email=f"load-{test_id}@example.com",
            full_name="Load Tester",
            workspace_id=ws_id,
        )
        session.add(user)
        await session.flush()

        repo = Repo(
            id=repo_id,
            name="load-target-service",
            owner="loadorg",
            workspace_id=ws_id,
            user_id=user_id,
            status="active",
        )
        session.add(repo)

        await session.commit()

    return ws_id, user_id, repo_id, test_id


async def benchmark_webhook_level(
    transport: httpx.ASGITransport,
    uid_token: str,
    secret: str,
    repo_name: str,
    concurrency: int,
    total_requests: int
) -> Dict[str, Any]:
    """Execute concurrent webhook requests against the PagerDuty webhook endpoint."""
    semaphore = asyncio.Semaphore(concurrency)
    latencies: List[float] = []
    status_codes: List[int] = []

    overall_start = time.perf_counter()
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=60.0) as client:
        async def send_single_webhook(idx: int):
            event_id = f"pd-load-{uuid.uuid4().hex[:12]}-{idx}"
            payload = {
                "event": {
                    "id": event_id,
                    "event_type": "incident.triggered",
                    "incident": {
                        "id": f"PD-INC-LOAD-{idx}",
                        "title": f"Load Spike Test #{idx}",
                        "service": {"summary": repo_name}
                    }
                }
            }
            raw_body = json.dumps(payload).encode("utf-8")
            sig = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()

            headers = {
                "Content-Type": "application/json",
                "X-PagerDuty-Signature": f"v1={sig}"
            }

            async with semaphore:
                start_t = time.perf_counter()
                try:
                    resp = await client.post(
                        f"{settings.API_PREFIX}/webhooks/pagerduty?uid={uid_token}",
                        content=raw_body,
                        headers=headers
                    )
                    elapsed = time.perf_counter() - start_t
                    latencies.append(elapsed * 1000.0)  # ms
                    status_codes.append(resp.status_code)
                except Exception as e:
                    elapsed = time.perf_counter() - start_t
                    latencies.append(elapsed * 1000.0)
                    status_codes.append(500)

        tasks = [send_single_webhook(i) for i in range(total_requests)]
        await asyncio.gather(*tasks)

    total_duration = time.perf_counter() - overall_start

    success_count = sum(1 for sc in status_codes if sc == 200)
    error_count = len(status_codes) - success_count
    throughput = len(status_codes) / total_duration if total_duration > 0 else 0.0

    sorted_latencies = sorted(latencies) if latencies else [0.0]
    p50 = statistics.median(sorted_latencies)
    p90 = sorted_latencies[int(len(sorted_latencies) * 0.90)]
    p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)]
    p99 = sorted_latencies[int(len(sorted_latencies) * 0.99)]

    return {
        "concurrency": concurrency,
        "total_requests": total_requests,
        "success_count": success_count,
        "error_count": error_count,
        "total_duration_s": round(total_duration, 3),
        "throughput_rps": round(throughput, 1),
        "min_ms": round(min(sorted_latencies), 1),
        "mean_ms": round(statistics.mean(sorted_latencies), 1),
        "p50_ms": round(p50, 1),
        "p90_ms": round(p90, 1),
        "p95_ms": round(p95, 1),
        "p99_ms": round(p99, 1),
        "max_ms": round(max(sorted_latencies), 1),
    }


async def benchmark_worker_throughput(ws_id: str, repo_id: str, batch_size: int = 50) -> Dict[str, Any]:
    """Benchmark Redis Stream background worker event consumption throughput."""
    await init_consumer_group()

    # Pre-create Event rows in DB
    event_ids: List[str] = []
    async with async_session() as session:
        await session.execute(text("RESET ROLE;"))
        await session.execute(text("SELECT set_config('nexops.bypass_rls', 'true', false);"))
        for i in range(batch_size):
            evt = Event(
                id=f"evt-load-stream-{uuid.uuid4().hex[:10]}-{i}",
                workspace_id=ws_id,
                repo_id=repo_id,
                type="ci.failed",
                source="load_test",
                message=f"Worker throughput benchmark event #{i}",
                created_at=datetime.now(timezone.utc),
            )
            session.add(evt)
            event_ids.append(evt.id)
        await session.commit()

    # Enqueue events to Redis Stream
    for evt_id in event_ids:
        await redis_client.xadd(
            STREAM_NAME,
            {"event_id": evt_id, "workspace_id": ws_id, "retry_count": "0"}
        )

    # Read from stream and process via worker handle_message
    worker_start = time.perf_counter()
    processed_count = 0

    # Read messages in batches
    while processed_count < batch_size:
        messages = await redis_client.xreadgroup(
            groupname=GROUP_NAME,
            consumername="load-test-worker",
            streams={STREAM_NAME: ">"},
            count=10,
            block=2000
        )
        if not messages:
            break

        for stream, msgs in messages:
            for msg_id, fields in msgs:
                fields_str = {
                    (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
                    for k, v in fields.items()
                }
                await handle_message(msg_id.decode() if isinstance(msg_id, bytes) else msg_id, fields_str)
                processed_count += 1

    worker_duration = time.perf_counter() - worker_start
    throughput = processed_count / worker_duration if worker_duration > 0 else 0.0

    return {
        "batch_size": batch_size,
        "processed_count": processed_count,
        "worker_duration_s": round(worker_duration, 3),
        "worker_throughput_eps": round(throughput, 1),
    }


async def main():
    # Enforce localhost only: strictly abort if target or databases are non-local
    verify_localhost_target()

    print("=" * 70)
    print("   NEXOPS PERFORMANCE BENCHMARK (LOCAL LOAD SUITE)")
    print("=" * 70)

    specs = get_machine_specs()
    print("\n[Machine & Environment Specifications]")
    for k, v in specs.items():
        print(f"  {k:18}: {v}")
    print("\n  >> IMPORTANT: Stamped as 'local, single machine'. Not production numbers. <<\n")

    # Disable rate limiter for raw throughput measurement
    limiter.enabled = False

    # Initialize Redis connection
    await init_redis()

    # Setup entities
    ws_id, user_id, repo_id, test_id = await setup_test_entities()
    secret = settings.PAGERDUTY_WEBHOOK_SECRET or "local-load-test-secret-key"
    settings.PAGERDUTY_WEBHOOK_SECRET = secret
    uid_token = _make_pd_uid_token(user_id)

    transport = httpx.ASGITransport(app=app)

    # 3 Load Levels: 10, 20, 30 concurrent requests (sized for local Postgres max_connections=100)
    load_levels = [
        {"concurrency": 10, "requests": 25},
        {"concurrency": 20, "requests": 40},
        {"concurrency": 30, "requests": 60},
    ]

    webhook_results = []
    print("-" * 70)
    print("PART 1: Webhook Ingestion Throughput (3 Concurrency Levels)")
    print("-" * 70)

    for lvl in load_levels:
        c = lvl["concurrency"]
        r = lvl["requests"]
        print(f"  Running Level (Concurrency={c:3}, Total Requests={r:3})...", end="", flush=True)
        res = await benchmark_webhook_level(
            transport=transport,
            uid_token=uid_token,
            secret=secret,
            repo_name="load-target-service",
            concurrency=c,
            total_requests=r
        )
        webhook_results.append(res)
        print(f" Done in {res['total_duration_s']}s -> {res['throughput_rps']} req/s (p50: {res['p50_ms']}ms, p95: {res['p95_ms']}ms, Success: {res['success_count']}/{res['total_requests']})")
        # Pause briefly to allow background tasks to drain before next concurrency tier
        await asyncio.sleep(2.0)

    # PART 2: Worker Stream Consumption
    print("\n" + "-" * 70)
    print("PART 2: Redis Stream Worker Processing Throughput")
    print("-" * 70)
    print("  Processing 50 pipeline events via handle_message loop...", end="", flush=True)
    worker_res = await benchmark_worker_throughput(ws_id=ws_id, repo_id=repo_id, batch_size=50)
    print(f" Done in {worker_res['worker_duration_s']}s -> {worker_res['worker_throughput_eps']} events/s\n")

    # Summary Table
    print("=" * 70)
    print("BENCHMARK SUMMARY (Classification: local, single machine)")
    print("=" * 70)
    print(f"{'Concurrency':<12} | {'Requests':<8} | {'Success':<8} | {'RPS':<10} | {'p50 (ms)':<9} | {'p95 (ms)':<9} | {'p99 (ms)':<9}")
    print("-" * 70)
    for wr in webhook_results:
        print(f"{wr['concurrency']:<12} | {wr['total_requests']:<8} | {wr['success_count']:<8} | {wr['throughput_rps']:<10} | {wr['p50_ms']:<9} | {wr['p95_ms']:<9} | {wr['p99_ms']:<9}")

    print("-" * 70)
    print(f"Worker Throughput: {worker_res['worker_throughput_eps']} events/sec (Batch: {worker_res['processed_count']} events in {worker_res['worker_duration_s']}s)")
    print("=" * 70)

    # Restore limiter setting
    limiter.enabled = True


if __name__ == "__main__":
    asyncio.run(main())
