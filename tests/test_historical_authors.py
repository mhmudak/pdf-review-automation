import json

import pytest

from historical_authors import (
    load_historical_author_map,
)


def test_no_map_config_returns_empty():
    assert (
        load_historical_author_map({})
        == {}
    )


def test_loads_entry_id_map(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "history.json"

    path.write_text(
        json.dumps(
            {
                "entry_id_to_author": {
                    "ID-1": "Hala Afifi",
                    "ID-2": "Hala Afifi",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "WORKFLOW2_HISTORICAL_AUTHOR_MAP",
        str(path),
    )

    result = load_historical_author_map(
        {}
    )

    assert result == {
        "ID-1": "Hala Afifi",
        "ID-2": "Hala Afifi",
    }


def test_missing_file_fails_closed(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "missing.json"

    monkeypatch.setenv(
        "WORKFLOW2_HISTORICAL_AUTHOR_MAP",
        str(path),
    )

    with pytest.raises(
        FileNotFoundError
    ):
        load_historical_author_map(
            {}
        )


def test_empty_author_fails_closed(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "history.json"

    path.write_text(
        json.dumps(
            {
                "ID-1": "",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "WORKFLOW2_HISTORICAL_AUTHOR_MAP",
        str(path),
    )

    with pytest.raises(
        ValueError
    ):
        load_historical_author_map(
            {}
        )
