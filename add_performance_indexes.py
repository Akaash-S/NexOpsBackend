"""
Performance Optimization: Add composite indexes for common query patterns
Run this script once to add indexes to existing database.
"""

import asyncio
from sqlalchemy import text
from app.core.database import engine


async def add_performance_indexes():
    """Add composite indexes to improve query performance."""
    
    indexes = [
        # Alerts: Common filter pattern (repo_id + resolved + severity)
        "CREATE INDEX IF NOT EXISTS idx_alerts_repo_resolved ON alerts(repo_id, resolved);",
        "CREATE INDEX IF NOT EXISTS idx_alerts_resolved_severity ON alerts(resolved, severity);",
        
        # Repos: Common filter patterns
        "CREATE INDEX IF NOT EXISTS idx_repos_workspace_cluster ON repos(workspace_id, cluster_id);",
        "CREATE INDEX IF NOT EXISTS idx_repos_platform ON repos(platform);",
        
        # Clusters: Workspace queries
        "CREATE INDEX IF NOT EXISTS idx_clusters_workspace ON clusters(workspace_id);",
        
        # Pipelines: Status queries
        "CREATE INDEX IF NOT EXISTS idx_pipelines_status ON pipelines(status);",
        "CREATE INDEX IF NOT EXISTS idx_pipelines_repo_status ON pipelines(repo_id, status);",
        
        # Events: Time-based queries
        "CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);",
        "CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(type, created_at DESC);",
    ]
    
    async with engine.begin() as conn:
        print("Adding performance indexes...")
        for idx_sql in indexes:
            try:
                await conn.execute(text(idx_sql))
                print(f"✓ {idx_sql.split('idx_')[1].split(' ')[0]}")
            except Exception as e:
                print(f"✗ Error: {e}")
        
        print("\n✅ Performance indexes added successfully!")


if __name__ == "__main__":
    asyncio.run(add_performance_indexes())
