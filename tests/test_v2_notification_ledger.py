import pytest

from v2_notification_ledger import (
    HEADERS,
    TAB,
    create_pending,
    delivery_decision,
    get_notification,
    transition,
)


class FakeSheets:
    def __init__(self):
        self.rows = [list(HEADERS)]
        self.write_count = 0

    def get_all_values(self, tab, refresh=False):
        assert tab == TAB
        return [list(row) for row in self.rows]

    def append_rows(self, tab, rows):
        assert tab == TAB
        self.rows.extend([list(row) for row in rows])
        self.write_count += 1

    def batch_update_rows(self, tab, updates):
        assert tab == TAB
        for row_number, row in updates:
            self.rows[row_number - 1] = list(row)
        self.write_count += 1


def pending(sheet, key="event-001"):
    return create_pending(
        sheet,
        key=key,
        document_key="TEST_DOC",
        kind="EXPORT_COMPLETED",
        recipient="admin@example.com",
        allow_writes=True,
    )


def test_new_notification_persisted_once():
    sheet = FakeSheets()
    assert pending(sheet)["State"] == "PENDING"
    assert pending(sheet)["State"] == "PENDING"
    assert sheet.write_count == 1


def test_delivery_cannot_start_without_persistence():
    sheet = FakeSheets()
    result = create_pending(
        sheet,
        key="event-001",
        document_key="TEST_DOC",
        kind="EXPORT_COMPLETED",
        recipient="admin@example.com",
    )
    assert delivery_decision(result) == "BLOCK_UNPERSISTED"
    assert sheet.write_count == 0


def test_sending_state_blocks_restart_resend():
    sheet = FakeSheets()
    pending(sheet)
    transition(
        sheet,
        key="event-001",
        expected_state="PENDING",
        new_state="SENDING",
        allow_writes=True,
    )
    assert delivery_decision(
        get_notification(sheet, "event-001")
    ) == "MANUAL_RECONCILIATION"


def test_sent_notification_cannot_be_resent():
    sheet = FakeSheets()
    pending(sheet)
    transition(
        sheet, key="event-001",
        expected_state="PENDING",
        new_state="SENDING",
        allow_writes=True,
    )
    transition(
        sheet, key="event-001",
        expected_state="SENDING",
        new_state="SENT",
        allow_writes=True,
    )
    assert delivery_decision(
        get_notification(sheet, "event-001")
    ) == "NOOP_ALREADY_SENT"
    assert pending(sheet)["State"] == "SENT"


def test_uncertain_delivery_requires_manual_review():
    sheet = FakeSheets()
    pending(sheet)
    transition(
        sheet, key="event-001",
        expected_state="PENDING",
        new_state="SENDING",
        allow_writes=True,
    )
    transition(
        sheet, key="event-001",
        expected_state="SENDING",
        new_state="DELIVERY_UNCERTAIN",
        error="SMTP timeout",
        allow_writes=True,
    )
    assert delivery_decision(
        get_notification(sheet, "event-001")
    ) == "MANUAL_RECONCILIATION"


def test_recipient_change_is_not_allowed_for_same_event():
    sheet = FakeSheets()
    pending(sheet)
    with pytest.raises(RuntimeError, match="IDENTITY_CONFLICT"):
        create_pending(
            sheet,
            key="event-001",
            document_key="TEST_DOC",
            kind="EXPORT_COMPLETED",
            recipient="pm@example.com",
            allow_writes=True,
        )


def test_duplicate_key_in_ledger_blocks_operations():
    sheet = FakeSheets()
    pending(sheet)
    sheet.rows.append(list(sheet.rows[1]))
    with pytest.raises(RuntimeError, match="INTEGRITY_ERROR"):
        get_notification(sheet, "event-001")


def test_missing_tab_schema_blocks_operations():
    sheet = FakeSheets()
    sheet.rows[0] = ["Incorrect header"]
    with pytest.raises(RuntimeError, match="SCHEMA_MISMATCH"):
        pending(sheet)


def test_invalid_transition_is_rejected():
    sheet = FakeSheets()
    pending(sheet)
    with pytest.raises(ValueError, match="INVALID"):
        transition(
            sheet, key="event-001",
            expected_state="PENDING",
            new_state="SENT",
            allow_writes=True,
        )


def test_repeated_admin_test_events_use_distinct_keys():
    sheet = FakeSheets()
    pending(sheet, "test-send-001")
    pending(sheet, "test-send-002")
    assert len(sheet.rows) == 3
    assert sheet.write_count == 2
