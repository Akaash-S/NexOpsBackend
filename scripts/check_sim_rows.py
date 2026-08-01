#!/usr/bin/env python3
"""Direct DB check: confirm synthetic simulation rows exist and show correlation output."""
import asyncio, os, sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    import asyncpg
except ImportError:
    sys.exit("pip install asyncpg")

async def query(url, sql):
    conn = await asyncpg.connect(url)
    try:
        return await conn.fetch(sql)
    finally:
        try:
            await conn.close()
        except Exception:
            pass

async def main():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL not set")

    # Events
    events = await query(url,
        "SELECT id, type, source, pd_event_id, pd_incident_id, created_at "
        "FROM events WHERE pd_event_id LIKE 'synthetic-sim-%' ORDER BY created_at DESC LIMIT 10"
    )
    print(f"\n=== EVENTS (synthetic-sim-*) === {len(events)} rows")
    for e in events:
        print(f"  id={e['id']}  type={e['type']}  pd_event_id={e['pd_event_id']}  pd_incident_id={e['pd_incident_id']}  created_at={e['created_at']}")

    # Incidents
    incs = await query(url,
        "SELECT id, title, status, pd_incident_id, workspace_id, created_at "
        "FROM incidents WHERE pd_incident_id LIKE 'SIM-%' ORDER BY created_at DESC LIMIT 10"
    )
    print(f"\n=== INCIDENTS (SIM-*) === {len(incs)} rows")
    for i in incs:
        print(f"  id={i['id']}  status={i['status']}  pd_incident_id={i['pd_incident_id']}  workspace_id={i['workspace_id']}  created_at={i['created_at']}")

    # Candidate Causes
    if incs:
        inc_ids = [i['id'] for i in incs]
        placeholders = ",".join(f"'{x}'" for x in inc_ids)
        ccs = await query(url,
            f"SELECT id, incident_id, score, reason, confirmed FROM candidate_causes "
            f"WHERE incident_id IN ({placeholders}) ORDER BY score DESC LIMIT 10"
        )
        print(f"\n=== CANDIDATE CAUSES === {len(ccs)} rows")
        for cc in ccs:
            print(f"  id={cc['id']}  incident_id={cc['incident_id']}  score={cc['score']}  confirmed={cc['confirmed']}")
            print(f"    reason={str(cc['reason'])[:140]}")

    # Feedback ledger
    if incs:
        inc_ids = [i['id'] for i in incs]
        placeholders = ",".join(f"'{x}'" for x in inc_ids)
        logs = await query(url,
            f"SELECT id, incident_id, candidate_cause_id, confirmed, score_at_time, created_at "
            f"FROM candidate_cause_feedback_logs WHERE incident_id IN ({placeholders}) LIMIT 10"
        )
        print(f"\n=== FEEDBACK LEDGER === {len(logs)} rows")
        for l in logs:
            print(f"  id={l['id']}  incident={l['incident_id']}  cc={l['candidate_cause_id']}  confirmed={l['confirmed']}  score={l['score_at_time']}  at={l['created_at']}")

asyncio.run(main())
