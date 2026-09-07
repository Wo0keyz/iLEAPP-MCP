from pydantic import BaseModel

from ileapp_mcp.case import CaseManager
from ileapp_mcp.modules.device_info import get_device_info
from ileapp_mcp.modules.networks import get_network_connections


class CloudIdentityProfile(BaseModel):
    device_name: str | None
    apple_ids: list[str]
    phone_numbers: list[str]
    imei: str | None
    serial_number: str | None
    wifi_networks: list[str]
    bluetooth_devices: list[str]


def get_cloud_identities(case: CaseManager) -> CloudIdentityProfile:
    """Aggregate identity and network profiles across the device."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    device = get_device_info(case)

    apple_ids = set()
    # Query accounts
    for tsv_path in case.get_all_tsv_files():
        if "account" in tsv_path.stem.lower():
            for row in case.read_tsv_records(tsv_path):
                for v in row.values():
                    if isinstance(v, str) and "@" in v and "." in v.split("@")[-1]:
                        apple_ids.add(v.strip().lower())

    networks_res = get_network_connections(case, limit=250)
    wifi = set()
    bt = set()
    for net in networks_res.items:
        if net.connection_type.lower() == "wifi" and net.ssid_or_name:
            wifi.add(net.ssid_or_name)
        elif net.connection_type.lower() == "bluetooth" and net.ssid_or_name:
            bt.add(net.ssid_or_name)

    phone_numbers = set()
    if device.phone_number:
        phone_numbers.add(device.phone_number)

    return CloudIdentityProfile(
        device_name=device.device_name,
        apple_ids=sorted(apple_ids),
        phone_numbers=sorted(phone_numbers),
        imei=device.imei,
        serial_number=device.serial_number,
        wifi_networks=sorted(wifi),
        bluetooth_devices=sorted(bt),
    )
