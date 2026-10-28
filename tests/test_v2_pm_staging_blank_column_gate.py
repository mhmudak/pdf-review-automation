"""Fail-closed staging-only flag contract for PM column reuse."""
import ast
from pathlib import Path


def test_column_reuse_enabled_only_by_explicit_staging_opt_in():
    tree = ast.parse((Path(__file__).resolve().parents[1] / "src" /
                      "v2_pm_export_coordinator.py").read_text())
    coordinator = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and node.name == "export_verified_pm")
    assignments = [node for node in ast.walk(coordinator)
                   if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "reuse_verified_blank"
                           for t in node.targets)]
    assert len(assignments) == 1
    test = ast.unparse(assignments[0].value)
    assert "destination == STAGING_ID" in test
    assert "config.get('v2_pm_reuse_verified_blank_columns') is True" in test
    calls = [node for node in ast.walk(coordinator) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "apply"
             and any(isinstance(k.value, ast.Name) and k.arg == "reuse_trailing_blank"
                     and k.value.id == "reuse_verified_blank" for k in node.keywords)]
    assert len(calls) == 1
