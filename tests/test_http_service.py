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
