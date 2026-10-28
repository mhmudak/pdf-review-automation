from types import SimpleNamespace
import pytest
from v2_dry_run_limit import select_dry_run_pdfs


def _pdf(name, size):
    return SimpleNamespace(name=name, size=size, file_id=name)


def test_dry_run_cap_picks_smallest_pdf(monkeypatch):
    monkeypatch.setenv('WORKFLOW2_DRY_RUN_MAX_FILES', '1')
    result = select_dry_run_pdfs([_pdf('huge.pdf', 10000), _pdf('small.pdf', 10)])
    assert [p.name for p in result] == ['small.pdf']


def test_dry_run_cap_unset_preserves_original_order(monkeypatch):
    monkeypatch.delenv('WORKFLOW2_DRY_RUN_MAX_FILES', raising=False)
    original = [_pdf('first.pdf', 100), _pdf('second.pdf', 1)]
    assert select_dry_run_pdfs(original) is original


@pytest.mark.parametrize('value', ['0', '-1', '11', 'oops', '1.5'])
def test_dry_run_rejects_invalid_limit(monkeypatch, value):
    monkeypatch.setenv('WORKFLOW2_DRY_RUN_MAX_FILES', value)
    with pytest.raises(ValueError, match='INVALID_DRY_RUN_MAX_FILES'):
        select_dry_run_pdfs([_pdf('any.pdf', 20)])
