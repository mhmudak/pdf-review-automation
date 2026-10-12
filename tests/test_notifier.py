import os

from notifier import (
    build_body,
    build_subject,
    recipients_for_audience,
)


def test_admin_recipient(monkeypatch):
    monkeypatch.setenv(
        "ADMIN_EMAIL",
        "admin@example.com",
    )

    monkeypatch.delenv(
        "PM_EMAIL",
        raising=False,
    )

    recipients = recipients_for_audience(
        ["ADMIN"]
    )

    assert recipients == [
        "admin@example.com"
    ]


def test_pm_recipient(monkeypatch):
    monkeypatch.setenv(
        "PM_EMAIL",
        "pm@example.com",
    )

    monkeypatch.delenv(
        "ADMIN_EMAIL",
        raising=False,
    )

    recipients = recipients_for_audience(
        ["PM"]
    )

    assert recipients == [
        "pm@example.com"
    ]


def test_admin_and_pm_recipient(monkeypatch):
    monkeypatch.setenv(
        "ADMIN_EMAIL",
        "admin@example.com",
    )

    monkeypatch.setenv(
        "PM_EMAIL",
        "pm@example.com",
    )

    recipients = recipients_for_audience(
        [
            "ADMIN",
            "PM",
        ]
    )

    assert recipients == [
        "admin@example.com",
        "pm@example.com",
    ]


def test_subject_contains_severity_file_and_code():
    alert = {
        "severity": "WARNING",
        "file": "book.pdf",
        "code": "PAGE_MAPPING_UNRESOLVED",
    }

    subject = build_subject(alert)

    assert "WARNING" in subject
    assert "book.pdf" in subject
    assert "PAGE_MAPPING_UNRESOLVED" in subject


def test_body_contains_message():
    alert = {
        "severity": "ERROR",
        "file": "broken.pdf",
        "code": "PDF_PROCESSING_ERROR",
        "message": "Cannot open PDF",
        "pm_actionable": True,
    }

    body = build_body(alert)

    assert "Cannot open PDF" in body
    assert "broken.pdf" in body
    assert "Manual action required: Yes" in body