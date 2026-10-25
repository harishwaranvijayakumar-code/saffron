
import json
from urllib.error import HTTPError, URLError
from unittest.mock import patch

import pytest

from runs.github_adapter import (
    GitHubAdapterError,
    get_workflow_run,
    list_workflow_jobs,
)


TARGET = "repository:example/project/actions/runs/123"
PAYLOAD = {"workflow_run_id": 123}


@pytest.fixture(autouse=True)
def github_config(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv(
        "GITHUB_ALLOWED_REPOSITORIES",
        "example/project",
    )


def fake_response(data):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return json.dumps(data).encode("utf-8")

    return Response()


def test_get_workflow_run_uses_read_only_get():
    response_data = {
        "id": 123,
        "name": "CI",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "html_url": "https://github.com/example/project/actions/runs/123",
    }

    with patch(
        "runs.github_adapter.urlopen",
        return_value=fake_response(response_data),
    ) as mock_urlopen:
        result = get_workflow_run(PAYLOAD, TARGET)

    assert result["simulated"] is False
    assert result["provider"] == "github"
    assert result["repository"] == "example/project"
    assert result["workflow_run_id"] == 123
    assert result["conclusion"] == "success"

    request = mock_urlopen.call_args.args[0]
    assert request.get_method() == "GET"
    assert (
        "/repos/example/project/actions/runs/123"
        in request.full_url
    )
    assert mock_urlopen.call_args.kwargs["timeout"] > 0


def test_list_workflow_jobs_returns_bounded_job_data():
    response_data = {
        "total_count": 1,
        "jobs": [
            {
                "id": 456,
                "name": "Build",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-10-25T10:00:00Z",
                "completed_at": "2026-10-25T10:01:00Z",
                "steps": [
                    {
                        "name": "Checkout",
                        "status": "completed",
                        "conclusion": "success",
                        "number": 1,
                    }
                ],
            }
        ],
    }

    with patch(
        "runs.github_adapter.urlopen",
        return_value=fake_response(response_data),
    ) as mock_urlopen:
        result = list_workflow_jobs(PAYLOAD, TARGET)

    assert result["simulated"] is False
    assert result["repository"] == "example/project"
    assert result["workflow_run_id"] == 123
    assert result["total_count"] == 1
    assert result["jobs"][0]["name"] == "Build"
    assert result["jobs"][0]["steps"][0]["name"] == "Checkout"

    request = mock_urlopen.call_args.args[0]
    assert request.get_method() == "GET"
    assert "/jobs?per_page=100" in request.full_url


def test_rejects_repository_outside_allowlist():
    with pytest.raises(GitHubAdapterError) as error:
        get_workflow_run(
            PAYLOAD,
            "repository:other/project/actions/runs/123",
        )

    assert error.value.code == "GITHUB_REPOSITORY_NOT_ALLOWLISTED"


def test_rejects_malformed_allowlist(monkeypatch):
    monkeypatch.setenv(
        "GITHUB_ALLOWED_REPOSITORIES",
        "not-a-repository",
    )

    with pytest.raises(GitHubAdapterError) as error:
        get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_ALLOWLIST_INVALID"


def test_rejects_ambiguous_repository(monkeypatch):
    monkeypatch.setenv(
        "GITHUB_ALLOWED_REPOSITORIES",
        "example/project,example/another",
    )

    with pytest.raises(GitHubAdapterError) as error:
        get_workflow_run(
            PAYLOAD,
            "GitHub Actions workflow run 123",
        )

    assert error.value.code == "GITHUB_REPOSITORY_REQUIRED"


def test_rejects_missing_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN")

    with pytest.raises(GitHubAdapterError) as error:
        get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_TOKEN_NOT_CONFIGURED"


def test_rejects_invalid_workflow_run_id():
    for invalid_id in (0, -1, True, "123", None):
        with pytest.raises(GitHubAdapterError) as error:
            get_workflow_run(
                {"workflow_run_id": invalid_id},
                TARGET,
            )

        assert error.value.code == "WORKFLOW_RUN_ID_INVALID"


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, "GITHUB_AUTH_OR_PERMISSION_DENIED"),
        (403, "GITHUB_AUTH_OR_PERMISSION_DENIED"),
        (404, "GITHUB_RESOURCE_NOT_FOUND"),
        (429, "GITHUB_RATE_LIMITED"),
        (500, "GITHUB_UPSTREAM_ERROR"),
        (503, "GITHUB_UPSTREAM_ERROR"),
        (400, "GITHUB_HTTP_ERROR"),
    ],
)
def test_http_errors_are_sanitized(status_code, expected_code):
    response = HTTPError(
        url="https://api.github.com/private",
        code=status_code,
        msg="sensitive response text",
        hdrs=None,
        fp=None,
    )

    with patch(
        "runs.github_adapter.urlopen",
        side_effect=response,
    ):
        with pytest.raises(GitHubAdapterError) as error:
            get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == expected_code
    assert "sensitive response text" not in str(error.value)


def test_network_error_is_sanitized():
    with patch(
        "runs.github_adapter.urlopen",
        side_effect=URLError("private network details"),
    ):
        with pytest.raises(GitHubAdapterError) as error:
            get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_NETWORK_ERROR"
    assert "private network details" not in str(error.value)


def test_timeout_is_sanitized():
    with patch(
        "runs.github_adapter.urlopen",
        side_effect=TimeoutError("private timeout details"),
    ):
        with pytest.raises(GitHubAdapterError) as error:
            get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_NETWORK_ERROR"
    assert "private timeout details" not in str(error.value)


def test_oversized_response_is_rejected():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return b"x" * (size + 1)

    with patch(
        "runs.github_adapter.urlopen",
        return_value=FakeResponse(),
    ):
        with pytest.raises(GitHubAdapterError) as error:
            get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_RESPONSE_TOO_LARGE"


def test_invalid_json_is_rejected():
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size=-1):
            return b"not-json"

    with patch(
        "runs.github_adapter.urlopen",
        return_value=FakeResponse(),
    ):
        with pytest.raises(GitHubAdapterError) as error:
            get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_INVALID_RESPONSE"


def test_non_object_json_is_rejected():
    with patch(
        "runs.github_adapter.urlopen",
        return_value=fake_response(["unexpected", "list"]),
    ):
        with pytest.raises(GitHubAdapterError) as error:
            get_workflow_run(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_INVALID_RESPONSE"


def test_invalid_jobs_response_is_rejected():
    with patch(
        "runs.github_adapter.urlopen",
        return_value=fake_response({"jobs": "not-a-list"}),
    ):
        with pytest.raises(GitHubAdapterError) as error:
            list_workflow_jobs(PAYLOAD, TARGET)

    assert error.value.code == "GITHUB_INVALID_RESPONSE"


def test_token_is_not_added_to_url():
    with patch(
        "runs.github_adapter.urlopen",
        return_value=fake_response({"id": 123}),
    ) as mock_urlopen:
        get_workflow_run(PAYLOAD, TARGET)

    request = mock_urlopen.call_args.args[0]

    assert "test-token" not in request.full_url
    assert request.get_header("Authorization") == "Bearer test-token"
