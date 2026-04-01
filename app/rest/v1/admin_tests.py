"""Admin endpoints to execute curated ETL/S3 test scenarios."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/admin/tests", tags=["admin"])

_REPO_ROOT = Path(__file__).resolve().parents[3]

SCENARIOS: Dict[str, Dict[str, object]] = {
    "s3_paths": {
        "description": "Validate S3 path generation (v2-only).",
        "pytest_args": ["app/etl/s3/tests/test_s3_paths.py"],
        "needs_real_s3": False,
    },
    "lifecycle_fake": {
        "description": "Run org->project->ai_system->assessment flow with FakeS3.",
        "pytest_args": ["app/etl/s3/tests/test_lifecycle_flow.py", "-k", "fake"],
        "needs_real_s3": False,
    },
    "lifecycle_real": {
        "description": "Run org->project->ai_system->assessment flow on real S3.",
        "pytest_args": ["app/etl/s3/tests/test_lifecycle_flow.py", "-k", "real_s3"],
        "needs_real_s3": True,
    },
}


class RunTestsBody(BaseModel):
    scenarios: List[str]
    fail_fast: bool = False
    quiet: bool = True


def _check_admin_token(x_admin_token: Optional[str]) -> None:
    expected = os.getenv("ADMIN_TESTS_TOKEN")
    if not expected:
        return
    if x_admin_token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Invalid admin token"},
        )


def _run_pytest(pytest_args: List[str], *, needs_real_s3: bool, quiet: bool) -> Dict[str, object]:
    cmd = ["python", "-m", "pytest", *pytest_args, "--tb=short"]
    if quiet:
        cmd.append("-q")

    env = os.environ.copy()
    if needs_real_s3:
        env["RUN_REAL_S3_LIFECYCLE"] = "1"

    proc = subprocess.run(
        cmd,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    text = "\n".join([x for x in [out, err] if x]).strip()
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "command": " ".join(cmd),
        "output": text,
    }


@router.get("/scenarios", summary="List runnable admin test scenarios")
async def list_test_scenarios(x_admin_token: Optional[str] = Header(default=None)):
    _check_admin_token(x_admin_token)
    return {
        "scenarios": [
            {"name": name, **meta}
            for name, meta in SCENARIOS.items()
        ]
    }


@router.post("/run", summary="Run selected admin test scenarios")
async def run_test_scenarios(
    body: RunTestsBody,
    x_admin_token: Optional[str] = Header(default=None),
):
    _check_admin_token(x_admin_token)
    if not body.scenarios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION", "message": "scenarios must not be empty"},
        )

    invalid = [s for s in body.scenarios if s not in SCENARIOS]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION", "message": f"Unknown scenarios: {invalid}"},
        )

    results = []
    all_ok = True
    for name in body.scenarios:
        cfg = SCENARIOS[name]
        result = _run_pytest(
            cfg["pytest_args"],  # type: ignore[arg-type]
            needs_real_s3=bool(cfg["needs_real_s3"]),
            quiet=body.quiet,
        )
        row = {"scenario": name, **result}
        results.append(row)
        if not result["ok"]:
            all_ok = False
            if body.fail_fast:
                break

    return {"ok": all_ok, "results": results}
