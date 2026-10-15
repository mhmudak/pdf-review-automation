from __future__ import annotations

import os
import smtplib

from email.message import EmailMessage
from typing import Any


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def notification_mode() -> str:
    mode = os.getenv(
        "NOTIFICATION_MODE", "OFF"
    ).strip().upper()

    if mode not in {"OFF", "TEST", "FINAL", "PRODUCTION"}:
        raise RuntimeError("INVALID_NOTIFICATION_MODE")

    return mode


def notifications_enabled() -> bool:
    return (
        _bool_env("NOTIFICATIONS_ENABLED", False)
        and notification_mode() != "OFF"
    )


def recipients_for_audience(
    audience: list[str],
) -> list[str]:
    recipients: list[str] = []

    mode = notification_mode()

    if mode == "OFF":
        return []

    if mode == "TEST":
        admin = os.getenv("ADMIN_EMAIL", "").strip()
        if not admin:
            raise RuntimeError(
                "ADMIN_EMAIL_REQUIRED_FOR_TEST"
            )
        return [admin]

    if (
        mode == "FINAL"
        and not _bool_env(
            "PM_FINAL_TEST_AUTHORIZED", False
        )
    ):
        raise RuntimeError(
            "PM_FINAL_TEST_NOT_AUTHORIZED"
        )

    admin_email = os.getenv(
        "ADMIN_EMAIL",
        "",
    ).strip()

    pm_email = os.getenv(
        "PM_EMAIL",
        "",
    ).strip()

    if (
        "ADMIN" in audience
        and admin_email
    ):
        recipients.append(admin_email)

    if (
        "PM" in audience
        and pm_email
        and pm_email not in recipients
    ):
        recipients.append(pm_email)

    return recipients


def build_subject(
    alert: dict[str, Any],
) -> str:
    severity = str(
        alert.get(
            "severity",
            "INFO",
        )
    )

    file_name = str(
        alert.get(
            "file",
            "",
        )
    )

    code = str(
        alert.get(
            "code",
            "",
        )
    )

    prefix = {
        "TEST": "[TEST]",
        "FINAL": "[FINAL TEST]",
    }.get(notification_mode(), "")

    return (
        f"{prefix}[PDF Review][{severity}] "
        f"{file_name} - {code}"
    )


def build_body(
    alert: dict[str, Any],
) -> str:
    severity = alert.get(
        "severity",
        "INFO",
    )

    code = alert.get(
        "code",
        "",
    )

    file_name = alert.get(
        "file",
        "",
    )

    message = alert.get(
        "message",
        "",
    )

    actionable = (
        "Yes"
        if alert.get(
            "pm_actionable"
        )
        else "No"
    )

    return "\n".join(
        [
            "PDF Review Automation",
            "",
            f"Severity: {severity}",
            f"Code: {code}",
            f"PDF: {file_name}",
            "",
            str(message),
            "",
            f"Manual action required: {actionable}",
        ]
    )


def send_email(
    recipients: list[str],
    subject: str,
    body: str,
) -> None:

    if not recipients:
        return

    smtp_host = os.getenv(
        "SMTP_HOST",
        "smtp.gmail.com",
    )

    smtp_port = int(
        os.getenv(
            "SMTP_PORT",
            "465",
        )
    )

    smtp_username = os.getenv(
        "SMTP_USERNAME",
        "",
    ).strip()

    smtp_password = os.getenv(
        "SMTP_PASSWORD",
        "",
    ).strip()

    from_name = os.getenv(
        "SMTP_FROM_NAME",
        "PDF Review Automation",
    ).strip()

    if (
        not smtp_username
        or not smtp_password
    ):
        raise RuntimeError(
            "SMTP credentials are not configured."
        )

    msg = EmailMessage()

    msg["Subject"] = subject
    msg["From"] = (
        f"{from_name} <{smtp_username}>"
    )

    msg["To"] = ", ".join(
        recipients
    )

    msg.set_content(body)

    if smtp_port == 465:
        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            timeout=30,
        ) as smtp:
            smtp.login(
                smtp_username,
                smtp_password,
            )
            smtp.send_message(msg)
    
    else:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=30,
        ) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
    
            smtp.login(
                smtp_username,
                smtp_password,
            )
    
            smtp.send_message(msg)


def notify_alert(
    alert: dict[str, Any],
) -> dict[str, Any]:

    recipients = recipients_for_audience(
        alert.get(
            "audience",
            [],
        )
    )

    if not notifications_enabled():
        return {
            "sent": False,
            "reason": "notifications disabled",
            "recipients": recipients,
        }

    if not recipients:
        return {
            "sent": False,
            "reason": "no recipients configured",
            "recipients": [],
        }

    send_email(
        recipients,
        build_subject(alert),
        build_body(alert),
    )

    return {
        "sent": True,
        "recipients": recipients,
    }