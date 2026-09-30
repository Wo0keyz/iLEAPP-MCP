"""A server must only ever serve the case it was explicitly given."""

import tempfile
from pathlib import Path

import pytest

from ileapp_mcp import case as case_module
from ileapp_mcp.case import CaseManager


def test_no_implicit_resume_of_last_case(mock_case_dir: Path) -> None:
    first = CaseManager()
    first.load_case(mock_case_dir)
    first.close()

    fresh = CaseManager()
    assert not fresh.is_loaded
    assert fresh.case_path is None


def test_loading_a_case_leaves_no_index_cache(mock_case_dir: Path) -> None:
    before = set(Path(tempfile.gettempdir()).glob(".ileapp_index_*"))
    case = CaseManager()
    case.load_case(mock_case_dir)
    case.close()
    assert set(Path(tempfile.gettempdir()).glob(".ileapp_index_*")) == before


def test_index_truncation_is_reported(mock_case_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(case_module, "_MAX_FILES_TO_SCAN", 3)
    case = CaseManager()
    case.load_case(mock_case_dir)
    assert case.index_truncated
    case.close()

    monkeypatch.setattr(case_module, "_MAX_FILES_TO_SCAN", 2_000_000)
    full = CaseManager()
    full.load_case(mock_case_dir)
    assert not full.index_truncated
    full.close()
