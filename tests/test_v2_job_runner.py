import job_runner
import pytest


def test_job_requires_explicit_v2(monkeypatch):
    monkeypatch.delenv("WORKFLOW2_V2_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="EXPLICIT_V2"):
        job_runner.run_once(lambda: {})


def test_job_blocks_pm_emails(monkeypatch):
    monkeypatch.setenv("WORKFLOW2_V2_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "FINAL")
    with pytest.raises(PermissionError, match="NOT_AUTHORIZED"):
        job_runner.run_once(lambda: {})


def test_job_allows_staging_no_notifications(monkeypatch):
    monkeypatch.setenv("WORKFLOW2_V2_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("NOTIFICATION_MODE", "OFF")
    assert job_runner.run_once(lambda: {"files_seen": 0, "results": []})["files_seen"] == 0


def test_job_rejects_invalid_pipeline_result(monkeypatch):
    monkeypatch.setenv("WORKFLOW2_V2_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    with pytest.raises(RuntimeError, match="NOT_A_DICTIONARY"):
        job_runner.run_once(lambda: None)


def test_main_exits_failure_on_per_file_error(monkeypatch):
    monkeypatch.setattr(job_runner, "run_once", lambda: {
        "files_seen": 1, "results": [{"action": "ERROR"}]})
    assert job_runner.main() == 1


def test_main_exits_success_on_no_errors(monkeypatch):
    monkeypatch.setattr(job_runner, "run_once", lambda: {
        "files_seen": 1, "results": [{"action": "PROCESSED"}]})
    assert job_runner.main() == 0


def test_main_handles_exception(monkeypatch):
    def fail():
        raise RuntimeError("test failure")
    monkeypatch.setattr(job_runner, "run_once", fail)
    assert job_runner.main() == 1
