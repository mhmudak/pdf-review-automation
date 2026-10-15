import pytest

from v2_notification_dispatcher import dispatch_notification
from v2_notification_policy import decide_notification
from v2_notification_ledger import (
    HEADERS, TAB, get_notification, transition,
)


class FakeSheets:
    def __init__(self):
        self.rows = [list(HEADERS)]
        self.writes = 0

    def get_all_values(self, tab, refresh=False):
        assert tab == TAB
        return [list(row) for row in self.rows]

    def append_rows(self, tab, rows):
        assert tab == TAB
        self.rows.extend([list(row) for row in rows])
        self.writes += 1

    def batch_update_rows(self, tab, updates):
        assert tab == TAB
        for number, row in updates:
            self.rows[number - 1] = list(row)
        self.writes += 1


class FakeEmail:
    def __init__(self, fails=False):
        self.calls = []
        self.fails = fails

    def __call__(self, recipients, subject, body):
        self.calls.append((recipients, subject, body))
        if self.fails:
            raise TimeoutError("SMTP status unknown")


def event(event_id="upload-001"):
    return decide_notification(
        event_kind="IDENTICAL_UPLOAD",
        document_key="TEST_DOC",
        event_id=event_id,
    )


def send(sheets, intent, sender, mode="TEST", **kwargs):
    return dispatch_notification(
        sheets=sheets,
        intent=intent,
        mode=mode,
        admin_email="admin@example.com",
        pm_email="pm@example.com",
        send_email_fn=sender,
        allow_writes=True,
        **kwargs,
    )


def test_success_is_durable_and_single_delivery():
    sheets = FakeSheets()
    email = FakeEmail()
    intent = event()

    first = send(sheets, intent, email)
    second = send(sheets, intent, email)

    assert first["action"] == "SENT"
    assert second["action"] == "ALREADY_SENT"
    assert len(email.calls) == 1
    assert get_notification(
        sheets, intent["key"]
    )["State"] == "SENT"


def test_test_mode_never_sends_to_pm():
    sheets = FakeSheets()
    email = FakeEmail()

    send(sheets, event(), email)
    assert email.calls[0][0] == ["admin@example.com"]
    assert email.calls[0][1].startswith("[TEST]")


def test_repeated_distinct_admin_tests_are_permitted():
    sheets = FakeSheets()
    email = FakeEmail()

    send(sheets, event("test-001"), email)
    send(sheets, event("test-002"), email)

    assert len(email.calls) == 2
    assert len(sheets.rows) == 3


def test_smtp_failure_creates_uncertain_delivery():
    sheets = FakeSheets()
    email = FakeEmail(fails=True)
    intent = event()

    with pytest.raises(
        RuntimeError, match="DELIVERY_UNCERTAIN"
    ):
        send(sheets, intent, email)

    assert get_notification(
        sheets, intent["key"]
    )["State"] == "DELIVERY_UNCERTAIN"

    result = send(sheets, intent, email)
    assert result["action"] == "DELIVERY_REVIEW_REQUIRED"
    assert len(email.calls) == 1


def test_interrupted_sending_never_retries():
    sheets = FakeSheets()
    email = FakeEmail()
    intent = event()

    from v2_notification_ledger import create_pending

    create_pending(
        sheets, key=intent["key"],
        document_key="TEST_DOC",
        kind="IDENTICAL_UPLOAD",
        recipient="admin@example.com",
        allow_writes=True,
    )
    transition(
        sheets, key=intent["key"],
        expected_state="PENDING",
        new_state="SENDING",
        allow_writes=True,
    )

    result = send(sheets, intent, email)
    assert result["action"] == "DELIVERY_REVIEW_REQUIRED"
    assert not email.calls


def test_dry_run_performs_no_writes_or_email():
    sheets = FakeSheets()
    email = FakeEmail()

    result = dispatch_notification(
        sheets=sheets,
        intent=event(),
        mode="TEST",
        admin_email="admin@example.com",
        send_email_fn=email,
        allow_writes=False,
    )

    assert result["action"] == "DRY_RUN"
    assert sheets.writes == 0
    assert email.calls == []


def test_off_mode_is_silent():
    sheets = FakeSheets()
    email = FakeEmail()

    result = send(sheets, event(), email, mode="OFF")

    assert result["action"] == "MODE_OFF"
    assert sheets.writes == 0
    assert email.calls == []


def test_final_pm_mode_requires_authorization():
    sheets = FakeSheets()
    email = FakeEmail()

    with pytest.raises(RuntimeError, match="NOT_AUTHORIZED"):
        send(sheets, event(), email, mode="FINAL")

    assert email.calls == []
    assert sheets.writes == 0


def test_final_pm_delivery_when_authorized():
    sheets = FakeSheets()
    email = FakeEmail()

    result = send(
        sheets, event(), email,
        mode="FINAL",
        pm_final_test_authorized=True,
    )

    assert result["action"] == "SENT"
    assert email.calls[0][0] == ["pm@example.com"]
    assert email.calls[0][1].startswith("[FINAL TEST]")


def test_unverified_export_cannot_dispatch():
    with pytest.raises(ValueError, match="verified export"):
        decide_notification(
            event_kind="EXPORT_COMPLETED",
            document_key="TEST_DOC",
            export_id="unverified",
            export_verified=False,
        )
