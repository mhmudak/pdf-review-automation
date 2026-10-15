from types import SimpleNamespace

import pytest

import v2_pipeline_notifications as bridge
from v2_notification_ledger import HEADERS, TAB


class FakeSheets:
    def __init__(self):
        self.rows = [list(HEADERS)]

    def get_all_values(self, tab, refresh=False):
        assert tab == TAB
        return [list(row) for row in self.rows]

    def append_rows(self, tab, rows):
        assert tab == TAB
        self.rows.extend([list(row) for row in rows])

    def batch_update_rows(self, tab, updates):
        assert tab == TAB
        for number, row in updates:
            self.rows[number - 1] = list(row)


FILE = SimpleNamespace(
    file_id="drive-test-1",
    name="sample.pdf",
    modified_time="2026-10-15T12:00:00Z",
    size=123,
)

ALERT = {
    "code": "REVIEW_COMPLETED",
    "severity": "INFO",
    "message": "The PDF review is ready.",
    "audience": ["PM"],
}


def deliver(sheets, sender, **kwargs):
    return bridge.dispatch_pipeline_alert(
        alert=ALERT,
        file_meta=FILE,
        sheets=sheets,
        status="PROCESSED",
        verified_export_required=True,
        summary={"sha256": "a" * 64},
        sender=sender,
        **kwargs,
    )


def test_off_does_not_touch_ledger(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    monkeypatch.setenv("NOTIFICATION_MODE", "OFF")

    result = deliver(None, lambda *args: None)
    assert result["action"] == "NOTIFICATIONS_DISABLED"


def test_verified_success_goes_to_admin_in_test_mode(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("PM_EMAIL", "pm@example.com")

    sheets = FakeSheets()
    sent = []

    result = deliver(
        sheets,
        lambda recipients, subject, body:
            sent.append((recipients, subject, body)),
    )

    assert result["action"] == "SENT"
    assert sent[0][0] == ["admin@example.com"]
    assert len(sheets.rows) == 2


def test_success_event_deduplicates(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")

    sheets = FakeSheets()
    sent = []

    sender = lambda *args: sent.append(args)

    first = deliver(sheets, sender)
    second = deliver(sheets, sender)

    assert first["action"] == "SENT"
    assert second["action"] == "ALREADY_SENT"
    assert len(sent) == 1


def test_unverified_success_cannot_send(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")

    result = bridge.dispatch_pipeline_alert(
        alert=ALERT,
        file_meta=FILE,
        sheets=None,
        status="PROCESSED",
        verified_export_required=False,
    )

    assert result["action"] == "UNVERIFIED_V2_SUCCESS_BLOCKED"


def test_processing_error_routes_to_admin(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("PM_EMAIL", "pm@example.com")

    sent = []
    result = bridge.dispatch_pipeline_alert(
        alert=ALERT,
        file_meta=FILE,
        sheets=FakeSheets(),
        status="ERROR",
        verified_export_required=False,
        error="Source verification failed",
        sender=lambda *args: sent.append(args),
    )

    assert result["action"] == "SENT"
    assert sent[0][0] == ["admin@example.com"]


def test_uncertain_send_is_not_retried(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("NOTIFICATION_MODE", "TEST")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")

    sheets = FakeSheets()
    calls = []

    def fail(*args):
        calls.append(args)
        raise TimeoutError("SMTP response unknown")

    with pytest.raises(RuntimeError, match="DELIVERY_UNCERTAIN"):
        deliver(sheets, fail)

    result = deliver(sheets, fail)
    assert result["action"] == "DELIVERY_REVIEW_REQUIRED"
    assert len(calls) == 1
