import random
from typing import List

def generate_realistic_logs(repo_name: str, branch: str, status: str) -> str:
    """Generates a realistic multi-line log string for a pipeline execution."""
    
    stages = [
        ("[system] Initializing runner for {repo}...", 1.2),
        ("[git] Fetching branch: {branch}", 0.8),
        ("[git] Verifying checksums for branch HEAD...", 0.5),
        ("[build] Environment: ubuntu-latest | node:20.x", 0.4),
        ("[build] Executing lifecycle: pre-build", 2.1),
        ("[npm] Installing dependencies (npm ci)...", 12.5),
        ("[npm] added 842 packages in 12s", 0.2),
        ("[build] Starting build stage...", 1.5),
        ("[vite] building for production...", 8.4),
        ("[vite] transform (102) src/components/layout/Topbar.tsx", 0.3),
        ("[vite] transform (156) src/pages/cicd/index.tsx", 0.4),
        ("[vite] build complete in 15.2s", 0.1),
        ("[test] Running unit tests (vitest)...", 5.2),
        ("[test] 42 tests passed, 0 failed", 0.5),
    ]
    
    if status == "success":
        stages.extend([
            ("[deploy] Preparing production artifact...", 2.4),
            ("[deploy] Uploading to cluster: eu-west-1", 4.1),
            ("[deploy] Deployment verification: PASSED", 1.2),
            ("[system] Pipeline execution completed successfully.", 0.2)
        ])
    else:
        stages.extend([
            ("[test] FAIL src/components/layout/Topbar.test.tsx > Topbar > should render current workspace", 0.1),
            ("[test] TypeError: Cannot read properties of null (reading 'useMemo')", 0.1),
            ("[test] 41 tests passed, 1 failed", 0.5),
            ("[system] ERROR: Pipeline execution failed during test stage.", 0.2)
        ])

    log_lines = []
    for template, duration in stages:
        line = template.format(repo=repo_name, branch=branch)
        log_lines.append(line)
        
    return "\n".join(log_lines)
