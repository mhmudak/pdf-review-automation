from alerts import classify_pdf_result


def _codes(alerts):
    return {alert["code"] for alert in alerts}


def test_successful_pdf_creates_info_alert():
    alerts = classify_pdf_result(
        "book.pdf",
        {
            "reviewers": ["Osama Elamrety"],
            "pages_unresolved": [],
            "footer_mismatches": [],
            "master_mismatch_suspected": False,
            "pages_beyond_master": 0,
        },
        {
            "inserted": 10,
            "updated": 2,
            "unchanged": 5,
            "needs_review": 0,
        },
    )

    assert "PDF_PROCESSED" in _codes(alerts)

    info = next(
        alert
        for alert in alerts
        if alert["code"] == "PDF_PROCESSED"
    )

    assert info["severity"] == "INFO"
    assert "ADMIN" in info["audience"]
    assert "PM" in info["audience"]


def test_unresolved_reviewer_is_warning_for_admin_and_pm():
    alerts = classify_pdf_result(
        "unknown.pdf",
        {
            "reviewers": [],
            "pages_unresolved": [],
            "footer_mismatches": [],
            "master_mismatch_suspected": False,
            "pages_beyond_master": 0,
        },
        {
            "inserted": 1,
            "updated": 0,
            "unchanged": 0,
            "needs_review": 1,
        },
    )

    assert "REVIEWER_UNRESOLVED" in _codes(alerts)
    assert "NEEDS_REVIEW" in _codes(alerts)

    unresolved = next(
        alert
        for alert in alerts
        if alert["code"] == "REVIEWER_UNRESOLVED"
    )

    assert unresolved["severity"] == "WARNING"
    assert unresolved["pm_actionable"] is True
    assert set(unresolved["audience"]) == {
        "ADMIN",
        "PM",
    }


def test_master_mismatch_is_admin_only():
    alerts = classify_pdf_result(
        "changed-master.pdf",
        {
            "reviewers": ["Reviewer Name"],
            "pages_unresolved": list(range(1, 301)),
            "footer_mismatches": [],
            "master_mismatch_suspected": True,
            "mapping_coverage": 0.1176,
            "master_index_version": "sha256:test",
            "pages_beyond_master": 17,
        },
        {
            "inserted": 3,
            "updated": 0,
            "unchanged": 0,
            "needs_review": 3,
        },
    )

    assert "MASTER_INDEX_MISMATCH" in _codes(alerts)

    mismatch = next(
        alert
        for alert in alerts
        if alert["code"] == "MASTER_INDEX_MISMATCH"
    )

    assert mismatch["severity"] == "WARNING"
    assert mismatch["audience"] == ["ADMIN"]
    assert mismatch["pm_actionable"] is False


def test_footer_mismatch_is_admin_only():
    alerts = classify_pdf_result(
        "book.pdf",
        {
            "reviewers": ["Reviewer Name"],
            "pages_unresolved": [],
            "footer_mismatches": [17, 22],
            "master_mismatch_suspected": False,
            "pages_beyond_master": 0,
        },
        {
            "inserted": 2,
            "updated": 0,
            "unchanged": 0,
            "needs_review": 0,
        },
    )

    footer = next(
        alert
        for alert in alerts
        if alert["code"] == "PAGE_NUMBER_MISMATCH"
    )

    assert footer["audience"] == ["ADMIN"]
    assert footer["pm_actionable"] is False


def test_processing_error_is_admin_and_pm():
    alerts = classify_pdf_result(
        "broken.pdf",
        {},
        {},
        status="ERROR",
        error="Cannot open PDF",
    )

    assert len(alerts) == 1

    alert = alerts[0]

    assert alert["code"] == "PDF_PROCESSING_ERROR"
    assert alert["severity"] == "ERROR"
    assert set(alert["audience"]) == {
        "ADMIN",
        "PM",
    }
    assert alert["pm_actionable"] is True
    assert "Cannot open PDF" in alert["message"]


def test_pages_beyond_master_is_admin_info():
    alerts = classify_pdf_result(
        "long-book.pdf",
        {
            "reviewers": ["Reviewer Name"],
            "pages_unresolved": list(range(324, 351)),
            "footer_mismatches": [],
            "master_mismatch_suspected": False,
            "pages_beyond_master": 27,
        },
        {
            "inserted": 4,
            "updated": 0,
            "unchanged": 0,
            "needs_review": 4,
        },
    )

    beyond = next(
        alert
        for alert in alerts
        if alert["code"] == "PAGES_BEYOND_MASTER"
    )

    assert beyond["severity"] == "INFO"
    assert beyond["audience"] == ["ADMIN"]