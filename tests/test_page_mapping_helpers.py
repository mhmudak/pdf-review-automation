from src.extractor import _footer_check


def test_footer_verifies_numeric_book_page():
    assert _footer_check("210", ["210"]) == ("footer_verified", 1.0)


def test_footer_mismatch_lowers_confidence():
    assert _footer_check("210", ["211"]) == ("footer_mismatch", 0.6)


def test_non_numeric_book_label_does_not_force_footer_check():
    assert _footer_check("viii", ["8"]) == ("", 0.0)
