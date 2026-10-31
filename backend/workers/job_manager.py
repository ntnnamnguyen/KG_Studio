"""Bộ điều phối tiến trình chạy ngầm (Extraction & Training Job Manager)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable

from shared.text_utils import now_iso, uid


@dataclass
class JobRecord:
    job_id: str
    job_type: str
    project_name: str
    status: str = "running"
    progress: float = 0.0
    message: str = ""
    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""
    result: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def start_sync_job(
        self,
        job_type: str,
        project_name: str,
        fn: Callable[[Callable[[float, str], None]], dict],
    ) -> JobRecord:
        job = JobRecord(job_id=uid(), job_type=job_type, project_name=project_name)
        self._jobs[job.job_id] = job

        def report(progress: float, msg: str = "") -> None:
            job.progress = max(0.0, min(1.0, float(progress)))
            if msg:
                job.message = msg

        try:
            res = fn(report)
            job.status = "completed"
            job.progress = 1.0
            job.result = res or {}
            job.finished_at = now_iso()
        except Exception as exc:
            job.status = "failed"
            job.message = str(exc)
            job.finished_at = now_iso()
            raise
        return job

    def get_job(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in sorted(self._jobs.values(), key=lambda x: x.started_at, reverse=True)]


default_job_manager = JobManager()

