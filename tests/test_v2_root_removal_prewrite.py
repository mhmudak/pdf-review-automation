"""A removed ROOT must abort before any backend writes."""
from dataclasses import dataclass
from types import SimpleNamespace
import pytest
from v2_execution import reject_removed_active_roots, execute_v2_pdf


def change(relation, active="TRUE"):
    return SimpleNamespace(previous={"Relation Type": relation, "Active": active})


def prepared(*changes):
    return SimpleNamespace(change_plan=SimpleNamespace(removed=changes))


def test_active_root_removal_fails_closed():
    with pytest.raises(RuntimeError, match="SOURCE_ROOT_REMOVAL_REQUIRES_REVIEW"):
        reject_removed_active_roots(prepared(change("ROOT")))


def test_removed_reply_is_not_blocked():
    reject_removed_active_roots(prepared(change("REPLY")))


def test_previously_inactive_root_is_not_blocked():
    reject_removed_active_roots(prepared(change("ROOT", "FALSE")))


def test_multiple_changes_rejects_an_active_root():
    with pytest.raises(RuntimeError, match="SOURCE_ROOT_REMOVAL_REQUIRES_REVIEW"):
        reject_removed_active_roots(prepared(change("REPLY"), change("ROOT")))
