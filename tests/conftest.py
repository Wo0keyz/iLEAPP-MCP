from collections.abc import Generator
from pathlib import Path

import pytest

from ileapp_mcp.case import CaseManager
from tests.fixtures.generate_mock_ileapp import generate_mock_ileapp_case


@pytest.fixture(scope="session")
def mock_case_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Fixture providing a generated mock iLEAPP output folder."""
    base_dir = tmp_path_factory.mktemp("sample_ileapp_case")
    generate_mock_ileapp_case(base_dir)
    return base_dir


@pytest.fixture
def loaded_case(mock_case_dir: Path) -> Generator[CaseManager, None, None]:
    """Fixture providing an initialized and loaded CaseManager."""
    case = CaseManager()
    case.load_case(mock_case_dir)
    yield case
    case.close()
