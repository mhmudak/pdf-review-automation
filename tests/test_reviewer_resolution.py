from src.extractor import reviewer_name

ALIASES = {
    "emanz": "Eman Zahran",
    "Elamrityo": "Osama Elamrety",
    "Luma Hameed": "Luma Hameed",
}
GENERIC = {"user", "author", "reviewer", "unknown"}


def test_aliases_expand_to_full_name():
    assert reviewer_name("emanz", "", ALIASES, GENERIC) == "Eman Zahran"
    assert reviewer_name("Elamrityo", "", ALIASES, GENERIC) == "Osama Elamrety"


def test_full_name_is_preserved():
    assert reviewer_name("Luma Hameed", "", ALIASES, GENERIC) == "Luma Hameed"
    assert reviewer_name("Sara Khalil", "", ALIASES, GENERIC) == "Sara Khalil"


def test_generic_or_unknown_username_is_unresolved():
    assert reviewer_name("user", "", ALIASES, GENERIC) == ""
    assert reviewer_name("someusername", "", ALIASES, GENERIC) == ""


def test_filename_can_resolve_known_alias():
    assert reviewer_name("user", "", ALIASES, GENERIC, "IGCSE_ARABIC_2P_Elamrityo.pdf") == "Osama Elamrety"


def test_filename_can_resolve_clear_full_name():
    assert reviewer_name("user", "", ALIASES, GENERIC, "IGCSE_ARABIC_2P_Sara Khalil.pdf") == "Sara Khalil"
