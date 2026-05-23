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

def _run_subprocess_win32(executable, args, clean_env):
    """
    Runs the subprocess in a separate thread with a ProactorEventLoop.
    This is required on Windows when Uvicorn runs with the SelectorEventLoop (e.g. during reload).
    """
    async def _execute():
        process = await asyncio.create_subprocess_exec(
            executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
            env=clean_env
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
            exit_code = process.returncode
        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            stdout, stderr = b"", b"Execution timed out (5s limit)."
            exit_code = -1
        return stdout, stderr, exit_code

    # Set the event loop policy in this thread
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    new_loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(new_loop)
        return new_loop.run_until_complete(_execute())
    finally:
        new_loop.close()

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

    # Clean environment (remove sensitive environment variables like DATABASE_URL, ENCRYPTION_KEY)
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }
    # Preserve required system variables on Windows to prevent crashes
    for key in os.environ:
        if key.upper() in ["SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "PATHEXT", "WINDIR", "SYSTEM32", "USERPROFILE"]:
            clean_env[key] = os.environ[key]

    try:
        if data.language.lower() == "python":
            executable = sys.executable
            args = ["-I", tmp_path]
        else:
            executable = "node"
            # Node 20+ experimental permission model (only allow reading the tmp file, no write)
            args = [
                "--experimental-permission",
                f"--allow-fs-read={tmp_path}",
                "--allow-fs-write=none",
                tmp_path
            ]

        # Run the command with a timeout
        if sys.platform == "win32":
            stdout, stderr, exit_code = await asyncio.to_thread(
                _run_subprocess_win32, executable, args, clean_env
            )
        else:
            process = await asyncio.create_subprocess_exec(
                executable,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                env=clean_env
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)
                exit_code = process.returncode
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except Exception:
                    pass
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
