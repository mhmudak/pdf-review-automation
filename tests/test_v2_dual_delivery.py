import pytest
from v2_notification_policy import delivery_plan, decide_notification
from v2_notification_dispatcher import dispatch_notification
from v2_notification_ledger import HEADERS, TAB

class FakeSheets:
    def __init__(self):
        self.rows = [list(HEADERS)]
    def get_all_values(self, tab, refresh=False):
        assert tab == TAB
        return [list(r) for r in self.rows]
    def append_rows(self, tab, rows):
        assert tab == TAB
        self.rows.extend([list(r) for r in rows])
    def batch_update_rows(self, tab, updates):
        assert tab == TAB
        for row_number, row in updates:
            self.rows[row_number-1] = list(row)

def intent(name='event-1'):
    return decide_notification(event_kind='IDENTICAL_UPLOAD', document_key='DOC', event_id=name)

def deliver(sheets, sender, *, mode='FINAL', pm='pm@example.com', admin='admin@example.com', event=None):
    return dispatch_notification(sheets=sheets, intent=event or intent(), mode=mode, pm_email=pm, admin_email=admin, pm_final_test_authorized=True, send_email_fn=sender, allow_writes=True)

def test_final_pm_and_admin_single_send():
    sheets=FakeSheets(); calls=[]
    result=deliver(sheets, lambda *args: calls.append(args))
    assert result['action']=='SENT'
    assert calls[0][0]==['pm@example.com','admin@example.com']
    assert sheets.rows[1][3]=='pm@example.com | admin@example.com'
    assert deliver(sheets, lambda *args: calls.append(args))['action']=='ALREADY_SENT'
    assert len(calls)==1

def test_test_mode_admin_only():
    sheets=FakeSheets(); calls=[]
    deliver(sheets, lambda *args: calls.append(args),mode='TEST')
    assert calls[0][0]==['admin@example.com']

def test_missing_admin_blocks_pm_send():
    with pytest.raises(RuntimeError, match='ADMIN_EMAIL_NOT_CONFIGURED'):
        delivery_plan(intent(),mode='FINAL',pm_email='pm@example.com',pm_final_test_authorized=True)

def test_deduplicates_identical_recipients_case_insensitively():
    plan=delivery_plan(intent(),mode='FINAL',pm_email='SAME@example.com',admin_email='same@example.com',pm_final_test_authorized=True)
    assert plan['recipients']==['SAME@example.com']

def test_changed_recipient_configuration_requires_reconciliation():
    sheets=FakeSheets();calls=[]; event=intent()
    deliver(sheets,lambda *args: calls.append(args),event=event)
    with pytest.raises(RuntimeError,match='NOTIFICATION_EVENT_IDENTITY_CONFLICT'):
        deliver(sheets,lambda *args: calls.append(args),admin='another@example.com',event=event)
    assert len(calls)==1

def test_transport_failure_never_retries_two_recipient_event():
    sheets=FakeSheets();calls=[]
    def fail(*args):
        calls.append(args)
        raise TimeoutError('unknown SMTP delivery')
    with pytest.raises(RuntimeError,match='DELIVERY_UNCERTAIN'):
        deliver(sheets, fail)
    assert deliver(sheets, fail)['action']=='DELIVERY_REVIEW_REQUIRED'
    assert len(calls)==1
