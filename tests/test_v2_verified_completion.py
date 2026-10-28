from v2_pipeline_notifications import verified_completion_fallback


def route(verified=True, export_id="export-001"):
    return {
        "pm_export_result": {
            "verified": verified,
            "export_id": export_id,
        }
    }


def test_no_alert_creates_confirmation():
    result = verified_completion_fallback([], route())
    assert result["code"] == "PDF_EXPORT_VERIFIED"
    assert result["audience"] == ["PM"]


def test_existing_pm_alert_prevents_duplicate():
    alerts = [{
        "code": "REVIEW_REQUIRED",
        "audience": ["PM"],
    }]
    assert verified_completion_fallback(alerts, route()) is None


def test_admin_alert_does_not_replace_pm_confirmation():
    alerts = [{
        "code": "ADMIN_INFORMATION",
        "audience": ["ADMIN"],
    }]
    assert verified_completion_fallback(alerts, route()) is not None


def test_unverified_export_is_blocked():
    assert verified_completion_fallback([], route(False)) is None


def test_missing_export_identity_is_blocked():
    assert verified_completion_fallback([], route(True, "")) is None


def test_missing_export_result_is_blocked():
    assert verified_completion_fallback([], {}) is None


def test_audience_comparison_is_case_insensitive():
    alerts = [{"audience": ["pm"]}]
    assert verified_completion_fallback(alerts, route()) is None
