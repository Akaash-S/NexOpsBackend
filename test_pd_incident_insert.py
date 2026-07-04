"""
Test whether pd_incident_id is properly persisted during Event creation.
"""
import asyncio, uuid
from datetime import datetime
from sqlalchemy import text
from app.core.database import async_session
from app.models.event import Event

async def main():
    async with async_session() as session:
        # Create a fresh Event with pd_incident_id set
        test_event = Event(
            id=f"test-{uuid.uuid4()}",
            type="pagerduty.incident",
            repo_id="repo-001",
            source="pagerduty",
            pd_event_id=f"test-pd-ev-{uuid.uuid4().hex[:8]}",
            pd_incident_id="TEST-PD-INC-999",  # explicitly set
            message="Test pd_incident_id persistence",
            severity="error"
        )
        print(f"Created Event object:")
        print(f"  pd_event_id = {test_event.pd_event_id}")
        print(f"  pd_incident_id = {test_event.pd_incident_id}")
        
        session.add(test_event)
        await session.commit()
        await session.refresh(test_event)
        
        print(f"\nAfter commit + refresh:")
        print(f"  id = {test_event.id}")
        print(f"  pd_event_id = {test_event.pd_event_id}")
        print(f"  pd_incident_id = {test_event.pd_incident_id}")
        
        # Now query DB directly
        r = await session.execute(text(f"SELECT pd_event_id, pd_incident_id FROM events WHERE id = '{test_event.id}'"))
        row = r.fetchone()
        print(f"\nFrom DB query:")
        print(f"  pd_event_id = {row[0]}")
        print(f"  pd_incident_id = {repr(row[1])}")
        
        # Verify with raw SQLAlchemy inspect
        from sqlalchemy import inspect
        mapper = inspect(Event)
        cols = [c.name for c in mapper.columns]
        print(f"\nSQLAlchemy mapped columns: {cols}")
        
        # Check if pd_incident_id is in the columns
        if 'pd_incident_id' in cols:
            print("pd_incident_id IS in mapped columns")
        else:
            print("pd_incident_id IS NOT in mapped columns!")
            
        # Clean up test row
        await session.execute(text(f"DELETE FROM events WHERE id = '{test_event.id}'"))
        await session.commit()

asyncio.run(main())
