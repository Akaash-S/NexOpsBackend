import asyncio
import sys
import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.security import get_current_user

router = APIRouter(prefix="/execute", tags=["Executor"])

class ExecutionRequest(BaseModel):
    code: str
    language: str
    filename: Optional[str] = "main.py"

class ExecutionResponse(BaseModel):
    stdout: str
    stderr: str
    exit_code: int

@router.post("", response_model=ExecutionResponse)
async def execute_code(
    data: ExecutionRequest,
    user = Depends(get_current_user)
):
    """
    Executes the provided code in a temporary sandbox.
    Supports Python and Node.js.
    """
    if data.language.lower() not in ["python", "javascript", "typescript", "node"]:
        raise HTTPException(status_code=400, detail="Language not supported for execution.")

    # Create a temporary file to hold the code
    suffix = ".py" if data.language.lower() == "python" else ".js"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data.code.encode('utf-8'))
        tmp_path = tmp.name

    try:
        if data.language.lower() == "python":
            executable = sys.executable
            args = [tmp_path]
        else:
            executable = "node"
            args = [tmp_path]

        # Run the command with a timeout
        process = await asyncio.create_subprocess_exec(
            executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            exit_code = process.returncode
        except asyncio.TimeoutError:
            process.kill()
            stdout, stderr = b"", b"Execution timed out (5s limit)."
            exit_code = -1

        return ExecutionResponse(
            stdout=stdout.decode('utf-8', errors='replace'),
            stderr=stderr.decode('utf-8', errors='replace'),
            exit_code=exit_code if exit_code is not None else -1
        )

    finally:
        # Cleanup
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
