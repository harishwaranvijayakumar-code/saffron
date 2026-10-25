
"""Bounded, read-only GitHub REST API adapter for Saffron."""
from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_BASE = "https://api.github.com"
TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 1_000_000
MAX_JOBS = 100

_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)


class GitHubAdapterError(Exception):
    """Safe, stable error suitable for audit records."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _allowed_repositories() -> set[str]:
    raw = os.getenv("GITHUB_ALLOWED_REPOSITORIES", "")
    entries = [item.strip().lower() for item in raw.split(",")]

    if (
        not entries
        or any(not item for item in entries)
        or any(not _REPOSITORY_RE.fullmatch(item) for item in entries)
    ):
        raise GitHubAdapterError("GITHUB_ALLOWLIST_INVALID")

    return set(entries)


def _repository_from_target(target_resource: str) -> str:
    allowed = _allowed_repositories()
    target = (target_resource or "").strip()

    # Accepted examples:
    # repository:owner/repo/actions/runs/123
    # repo/owner/repo/actions/runs/123
    # https://github.com/owner/repo/actions/runs/123
    patterns = (
        r"^repository:([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/|$)",
        r"^repo/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/|$)",
        r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/|$)",
    )

    repository = None
    for pattern in patterns:
        match = re.match(pattern, target, flags=re.IGNORECASE)
        if match:
            repository = match.group(1).lower()
            break

    # Existing generic targets are only unambiguous if one repo is allowed.
    if repository is None:
        if len(allowed) != 1:
            raise GitHubAdapterError("GITHUB_REPOSITORY_REQUIRED")
        repository = next(iter(allowed))

    if repository not in allowed:
        raise GitHubAdapterError("GITHUB_REPOSITORY_NOT_ALLOWLISTED")

    return repository


def _get_json(path: str) -> dict:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise GitHubAdapterError("GITHUB_TOKEN_NOT_CONFIGURED")

    if (
        not path.startswith("/")
        or path.startswith("//")
        or ".." in path.split("/")
    ):
        raise GitHubAdapterError("GITHUB_PATH_INVALID")

    request = Request(
        f"{API_BASE}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Saffron-read-only-adapter",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)

        if len(raw) > MAX_RESPONSE_BYTES:
            raise GitHubAdapterError("GITHUB_RESPONSE_TOO_LARGE")

        data = json.loads(raw.decode("utf-8"))

    except HTTPError as exc:
        # Never include response bodies, headers, or token in errors.
        if exc.code in (401, 403):
            code = "GITHUB_AUTH_OR_PERMISSION_DENIED"
        elif exc.code == 404:
            code = "GITHUB_RESOURCE_NOT_FOUND"
        elif exc.code == 429:
            code = "GITHUB_RATE_LIMITED"
        elif 500 <= exc.code <= 599:
            code = "GITHUB_UPSTREAM_ERROR"
        else:
            code = "GITHUB_HTTP_ERROR"
        raise GitHubAdapterError(code) from None

    except (TimeoutError, URLError, OSError):
        raise GitHubAdapterError("GITHUB_NETWORK_ERROR") from None

    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GitHubAdapterError("GITHUB_INVALID_RESPONSE") from None

    if not isinstance(data, dict):
        raise GitHubAdapterError("GITHUB_INVALID_RESPONSE")

    return data


def _workflow_run_id(payload: dict) -> int:
    value = payload.get("workflow_run_id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GitHubAdapterError("WORKFLOW_RUN_ID_INVALID")
    return value


def get_workflow_run(payload: dict, target_resource: str) -> dict:
    run_id = _workflow_run_id(payload)
    repository = _repository_from_target(target_resource)

    data = _get_json(
        f"/repos/{repository}/actions/runs/{run_id}"
    )

    # Explicit response allowlist: do not return the entire API response.
    return {
        "simulated": False,
        "provider": "github",
        "repository": repository,
        "workflow_run_id": data.get("id"),
        "name": data.get("name"),
        "event": data.get("event"),
        "status": data.get("status"),
        "conclusion": data.get("conclusion"),
        "html_url": data.get("html_url"),
        "run_number": data.get("run_number"),
        "head_branch": data.get("head_branch"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def list_workflow_jobs(payload: dict, target_resource: str) -> dict:
    run_id = _workflow_run_id(payload)
    repository = _repository_from_target(target_resource)

    data = _get_json(
        f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page={MAX_JOBS}"
    )

    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise GitHubAdapterError("GITHUB_INVALID_RESPONSE")

    safe_jobs = []
    for job in jobs[:MAX_JOBS]:
        if not isinstance(job, dict):
            continue

        raw_steps = job.get("steps")
        if not isinstance(raw_steps, list):
            raw_steps = []

        safe_jobs.append({
            "id": job.get("id"),
            "name": job.get("name"),
            "status": job.get("status"),
            "conclusion": job.get("conclusion"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "html_url": job.get("html_url"),
            "steps": [
                {
                    "name": step.get("name"),
                    "status": step.get("status"),
                    "conclusion": step.get("conclusion"),
                    "number": step.get("number"),
                }
                for step in raw_steps[:MAX_JOBS]
                if isinstance(step, dict)
            ],
        })

    return {
        "simulated": False,
        "provider": "github",
        "repository": repository,
        "workflow_run_id": run_id,
        "total_count": data.get("total_count", len(safe_jobs)),
        "jobs": safe_jobs,
    }
