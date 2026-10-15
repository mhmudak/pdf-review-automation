import pytest

from notifier import (
    build_subject,
    notification_mode,
    notifications_enabled,
    recipients_for_audience,
)


def configure(monkeypatch, mode):
    monkeypatch.setenv("NOTIFICATION_MODE", mode)
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("PM_EMAIL", "pm@example.com")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "true")


def test_default_off(monkeypatch):
    monkeypatch.delenv("NOTIFICATION_MODE", raising=False)
    assert notification_mode() == "OFF"
    assert not notifications_enabled()


def test_disabled_flag_blocks_sending(monkeypatch):
    configure(monkeypatch, "TEST")
    monkeypatch.setenv("NOTIFICATIONS_ENABLED", "false")
    assert not notifications_enabled()


def test_test_mode_pm_alert_goes_only_to_admin(monkeypatch):
    configure(monkeypatch, "TEST")
    assert recipients_for_audience(["PM"]) == [
        "admin@example.com"
    ]


def test_test_mode_both_audiences_still_one_email(monkeypatch):
    configure(monkeypatch, "TEST")
    assert recipients_for_audience(["ADMIN", "PM"]) == [
        "admin@example.com"
    ]


def test_test_mode_subject_is_marked(monkeypatch):
    configure(monkeypatch, "TEST")
    subject = build_subject({
        "severity": "INFO",
        "file": "test.pdf",
        "code": "CHECKED",
    })
    assert subject.startswith("[TEST]")


def test_final_mode_blocks_pm_until_authorized(monkeypatch):
    configure(monkeypatch, "FINAL")
    monkeypatch.delenv(
        "PM_FINAL_TEST_AUTHORIZED", raising=False
    )
    with pytest.raises(RuntimeError, match="NOT_AUTHORIZED"):
        recipients_for_audience(["PM"])


def test_final_mode_allows_explicit_pm_authorization(monkeypatch):
    configure(monkeypatch, "FINAL")
    monkeypatch.setenv(
        "PM_FINAL_TEST_AUTHORIZED", "true"
    )
    assert recipients_for_audience(["PM"]) == [
        "pm@example.com"
    ]


def test_production_audience_routing(monkeypatch):
    configure(monkeypatch, "PRODUCTION")
    assert recipients_for_audience(["ADMIN"]) == [
        "admin@example.com"
    ]
    assert recipients_for_audience(["PM"]) == [
        "pm@example.com"
    ]


def test_invalid_mode_fails_closed(monkeypatch):
    configure(monkeypatch, "INVALID")
    with pytest.raises(RuntimeError, match="INVALID"):
        notifications_enabled()


def test_test_mode_requires_admin_address(monkeypatch):
    configure(monkeypatch, "TEST")
    monkeypatch.delenv("ADMIN_EMAIL")
    with pytest.raises(RuntimeError, match="ADMIN_EMAIL"):
        recipients_for_audience(["PM"])
