from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.photos import get_photos_metadata


def test_get_photos(loaded_case: CaseManager) -> None:
    res = get_photos_metadata(loaded_case)
    assert res.total_count == 2
    assert len(res.items) == 2
    assert any(item.file_name == "IMG_0001.HEIC" for item in res.items)


def test_get_photos_deleted(loaded_case: CaseManager) -> None:
    res = get_photos_metadata(loaded_case, is_deleted=True)
    assert res.total_count == 1
    assert res.items[0].file_name == "IMG_0002.HEIC"


def test_get_photos_gps(loaded_case: CaseManager) -> None:
    res = get_photos_metadata(loaded_case, has_gps=True)
    assert res.total_count == 1
    assert res.items[0].latitude == 48.8584
