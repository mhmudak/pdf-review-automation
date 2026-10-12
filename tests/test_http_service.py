from unittest.mock import patch

import http_service


def test_health_endpoint():
    client = (
        http_service.app.test_client()
    )

    response = client.get(
        "/health"
    )

    assert response.status_code == 200
    assert (
        response.get_json()["status"]
        == "ok"
    )


def test_root_is_health():
    client = (
        http_service.app.test_client()
    )

    response = client.get("/")

    assert response.status_code == 200


def test_run_calls_pipeline():
    client = (
        http_service.app.test_client()
    )

    with patch.object(
        http_service,
        "_run_pipeline",
        return_value={
            "files_seen": 0,
            "results": [],
        },
    ) as mocked:
        response = client.post(
            "/run"
        )

    assert response.status_code == 200

    body = response.get_json()

    assert body["status"] == "ok"
    assert (
        body["result"]["files_seen"]
        == 0
    )

    mocked.assert_called_once()


def test_run_returns_500_on_failure():
    client = (
        http_service.app.test_client()
    )

    with patch.object(
        http_service,
        "_run_pipeline",
        side_effect=RuntimeError(
            "test failure"
        ),
    ):
        response = client.post(
            "/run"
        )

    assert response.status_code == 500
    assert (
        response.get_json()["status"]
        == "error"
    )


def test_get_run_is_not_allowed():
    client = (
        http_service.app.test_client()
    )

    response = client.get(
        "/run"
    )

    assert response.status_code == 405

def test_run_pipeline_passes_both_spreadsheets(
    monkeypatch,
):
    from pathlib import Path

    monkeypatch.setenv(
        "WORKFLOW2_DRIVE_FOLDER_ID",
        "folder-123",
    )

    monkeypatch.setenv(
        "WORKFLOW2_SPREADSHEET_ID",
        "backend-123",
    )

    monkeypatch.setenv(
        "WORKFLOW2_OUTPUT_SPREADSHEET_ID",
        "output-123",
    )

    monkeypatch.delenv(
        "WORKFLOW2_DRY_RUN",
        raising=False,
    )

    with patch.object(
        http_service,
        "_paths",
        return_value=(
            Path("master.json"),
            Path("config.json"),
        ),
    ), patch.object(
        http_service,
        "process_drive_folder",
        return_value={
            "files_seen": 0,
            "results": [],
        },
    ) as mocked:

        result = (
            http_service._run_pipeline()
        )

    mocked.assert_called_once_with(
        "folder-123",
        "backend-123",
        "output-123",
        Path("master.json"),
        Path("config.json"),
        False,
    )

    assert result["files_seen"] == 0
