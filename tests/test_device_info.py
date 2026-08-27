from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.device_info import get_device_info


def test_get_device_info(loaded_case: CaseManager) -> None:
    info = get_device_info(loaded_case)

    assert info.device_name == "iPhone 14 Pro de John Doe"
    assert info.product_type == "iPhone15,2"
    assert info.ios_version == "17.4.1 (21E236)"
    assert info.serial_number == "F2LL70ABCD12"
    assert info.imei == "354890123456789"
    assert info.phone_number == "+33612345678"
    assert "Paris" in (info.timezone or "")
    assert "GrayKey" in (info.extraction_type or "")
    assert len(info.raw_metadata) >= 8
