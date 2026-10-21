"""Scheduled jobs (ADR-018): `%LOCALAPPDATA%\\lfmap\\jobs.toml` and the Windows Task Scheduler commands for it.

Task Scheduler does the scheduling; each task runs `scripts/Invoke-LfmapJob.ps1`, which calls `lfmap jobs run`.
Only tasks in the `\\LFMAP\\` folder are ever created or deleted. A job never asks anyone: calls above its
`max_tier` become proposals in the approval queue (`lfmap_core.approvals`).
"""

import csv
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from lfmap_core.approval import Policy, base_tier
from lfmap_core.approvals import JobApprover, ttl
from lfmap_core.config import app_dir, load_config
from lfmap_core.errors import ToolError
from lfmap_core.registry import PluginEntry, Registry
from lfmap_core.runtime import run_operation

TASK_FOLDER = "\\LFMAP\\"
QUERY = ["schtasks", "/Query", "/FO", "CSV", "/NH"]
MAX_ACTION = 261  # schtasks /TR limit
_ID = r"^[a-z][a-z0-9-]*$"
_TIME = r"([01]\d|2[0-3]):[0-5]\d"
_DAILY = re.compile(rf"^{_TIME}$")
_WEEKLY = re.compile(rf"^(MON|TUE|WED|THU|FRI|SAT|SUN) {_TIME}$")


class Schedule(BaseModel):
    """Exactly one of `daily = "HH:MM"`, `weekly = "MON HH:MM"` or `every_minutes = n`."""

    model_config = ConfigDict(extra="forbid")

    daily: str | None = None
    weekly: str | None = None
    every_minutes: int | None = Field(None, ge=1, le=1439)

    @field_validator("daily")
    @classmethod
    def _daily(cls, value: str | None) -> str | None:
        if value is not None and not _DAILY.match(value):
            raise ValueError("daily must look like 07:30")
        return value

    @field_validator("weekly")
    @classmethod
    def _weekly(cls, value: str | None) -> str | None:
        if value is not None and not _WEEKLY.match(value):
            raise ValueError("weekly must look like MON 07:30")
        return value

    @model_validator(mode="after")
    def _one_kind(self) -> "Schedule":
        if sum(v is not None for v in (self.daily, self.weekly, self.every_minutes)) != 1:
            raise ValueError("schedule needs exactly one of daily, weekly, every_minutes")
        return self

    def describe(self) -> str:
        if self.daily:
            return f"daily {self.daily}"
        if self.weekly:
            return f"weekly {self.weekly}"
        return f"every {self.every_minutes} min"

    def task_args(self) -> list[str]:
        if self.daily:
            return ["/SC", "DAILY", "/ST", self.daily]
        if self.weekly:
            day, time = self.weekly.split()
            return ["/SC", "WEEKLY", "/D", day, "/ST", time]
        return ["/SC", "MINUTE", "/MO", str(self.every_minutes)]


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ID)
    plugin: str
    operation: str
    input: dict[str, Any] = Field(default_factory=dict)
    schedule: Schedule
    max_tier: Literal[0, 1] = 0
    enabled: bool = True


class JobsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[Job] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self) -> "JobsFile":
        ids = [job.id for job in self.jobs]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate job ids: {', '.join(duplicates)}")
        return self


def jobs_path() -> Path:
    override = os.environ.get("LFMAP_JOBS")
    return Path(override) if override else app_dir() / "jobs.toml"


def load_jobs(path: Path | None = None) -> list[Job]:
    path = path or jobs_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        return JobsFile.model_validate(tomllib.loads(text)).jobs
    except tomllib.TOMLDecodeError as error:
        raise ToolError("invalid_input", f"{path} is not valid TOML", {"error": str(error)}) from error
    except ValidationError as error:
        raise ToolError("invalid_input", f"{path} is invalid", {"error": str(error)}) from error


def check_input(entry: PluginEntry, operation: str, payload: dict[str, Any]) -> None:
    """Refuse input that does not match the operation before anything is queued or approved."""
    spec = entry.tool_class.operations().get(operation)
    if spec is None:
        raise ToolError("not_found", f"Unknown operation {entry.id}.{operation}", {"operation": operation})
    try:
        spec.input_model.model_validate(payload)
    except ValidationError as error:
        details = {"operation": f"{entry.id}.{operation}", "errors": error.errors(include_context=False)}
        raise ToolError("invalid_input", "Input does not match the operation schema", details) from error


def run_job(registry: Registry, job_id: str, path: Path | None = None) -> BaseModel:
    job = next((j for j in load_jobs(path) if j.id == job_id), None)
    if job is None:
        raise ToolError("not_found", f"Unknown job {job_id!r}", {"job": job_id})
    if not job.enabled:
        raise ToolError("invalid_input", f"Job {job_id!r} is disabled", {"job": job_id})
    entry = registry.get(job.plugin)
    declared = entry.manifest.operation(job.operation)
    if declared is None:
        raise ToolError("not_found", f"Unknown operation {job.plugin}.{job.operation}", {"job": job_id})
    check_input(entry, job.operation, job.input)
    config = load_config()
    gate = JobApprover(job, Policy.from_config(config), ttl(config))
    gate(base_tier(declared.side_effects), "side_effects")
    return run_operation(entry, job.operation, job.input, channel="job", approver=gate)


def task_command(job: Job, repo: Path, uv: Path, script: Path) -> list[str]:
    action = f'pwsh -NoProfile -File "{script}" -JobId {job.id} -RepoPath "{repo}" -UvPath "{uv}"'
    if len(action) > MAX_ACTION:
        raise ToolError("invalid_input", f"Task action is longer than {MAX_ACTION} characters", {"action": action})
    return ["schtasks", "/Create", "/TN", TASK_FOLDER + job.id, "/TR", action, *job.schedule.task_args(), "/F"]


def delete_command(job_id: str) -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK_FOLDER + job_id, "/F"]


def registered_tasks(query_csv: str) -> set[str]:
    """Job ids of tasks directly in `\\LFMAP\\`; any other task is never ours to touch."""
    ids = set()
    for row in csv.reader(query_csv.splitlines()):
        name = row[0] if row else ""
        job_id = name.removeprefix(TASK_FOLDER)
        if name.startswith(TASK_FOLDER) and re.fullmatch(_ID, job_id):
            ids.add(job_id)
    return ids


def register_commands(jobs: list[Job], existing: set[str], repo: Path, uv: Path, script: Path) -> list[list[str]]:
    """Create a task for every enabled job; delete existing tasks whose job is disabled or gone."""
    enabled = [job for job in jobs if job.enabled]
    stale = existing - {job.id for job in enabled}
    return [task_command(job, repo, uv, script) for job in enabled] + [delete_command(i) for i in sorted(stale)]


def _schtasks(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, errors="replace", check=False)
    except FileNotFoundError as error:
        raise ToolError("backend_unavailable", "schtasks was not found (Windows only)") from error
    if result.returncode != 0:
        details = {"command": subprocess.list2cmdline(args), "stderr": result.stderr.strip()}
        raise ToolError("internal", f"schtasks exited with {result.returncode}", details)
    return result.stdout


def existing_tasks() -> set[str]:
    return registered_tasks(_schtasks(QUERY))


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def find_uv() -> Path:
    """`uv` on PATH, then the WinGet link; the same rule as `scripts/Invoke-LfmapJob.ps1`."""
    found = shutil.which("uv")
    if found:
        return Path(found)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    winget = Path(base) / "Microsoft" / "WinGet" / "Links" / "uv.exe"
    if winget.is_file():
        return winget
    raise ToolError("not_found", "uv was not found; pass --uv", {"tried": ["PATH", str(winget)]})
