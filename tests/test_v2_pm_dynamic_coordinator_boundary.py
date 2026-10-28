"""Regression checks for the legacy/dynamic planning boundary."""
import ast
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'src' / 'v2_pm_export_coordinator.py'
module = ast.parse(source.read_text(encoding='utf-8'))
function = next(x for x in module.body if isinstance(x, ast.FunctionDef)
                and x.name == 'legacy_source_for_dynamic_planner')
namespace = {'clean': lambda v: '' if v is None else str(v)}
exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
normalize = namespace['legacy_source_for_dynamic_planner']


def test_prior_reply_fields_isolated_from_legacy_planner():
    old = [{'Root Entry ID':'r', 'Comment':'old', 'Reply 1':'old1', 'Reply Entry IDs':'id1'}]
    new = [{'Root Entry ID':'r', 'Comment':'new', 'Reply 1':'edited',
            'Reply 2':'second', 'Reply Entry IDs':'id1 | id2'}]
    got = normalize(old, new)
    assert got[0]['Comment'] == 'new'
    assert got[0]['Reply 1'] == 'old1'
    assert got[0]['Reply 2'] == ''
    assert got[0]['Reply Entry IDs'] == 'id1'
    assert new[0]['Reply 1'] == 'edited'


def test_new_root_remains_unmodified():
    old = [{'Root Entry ID':'a'}]
    new = [{'Root Entry ID':'a'}, {'Root Entry ID':'b', 'Reply 4':'new'}]
    assert normalize(old, new)[1] == new[1]


def test_no_reply_changes_for_existing_rows():
    old = [{'Root Entry ID':'a', 'Reply 1':'same', 'Reply Entry IDs':'id1'}]
    assert normalize(old, list(old)) == old
