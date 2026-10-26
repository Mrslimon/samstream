import json
from pathlib import Path
from typing import Any

from aiosamstream import DeviceInfo

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def test_qn800c_payload() -> None:
    info = DeviceInfo.from_api(load("device_info_qn800c.json"))

    assert info.uuid == "00000000-0000-0000-0000-000000000002"
    assert info.name == '65" Neo QLED 8K'
    assert info.model_name == "QA65QN800CUXEG"
    assert info.year == 2023
    assert info.firmware is None
    assert info.mac == "aa:bb:cc:00:11:22"
    assert info.power_on is True
    assert info.developer_mode is True
    assert info.developer_ip == "192.168.1.21"
    assert info.token_auth is True
    assert info.network_type == "wireless"


def test_old_tv_without_power_state_or_developer_fields() -> None:
    info = DeviceInfo.from_api(
        {"id": "uuid:abc", "device": {"name": "TV", "model": "16_JAZZM_UHD"}}
    )

    assert info.uuid == "abc"
    assert info.year == 2016
    assert info.power_on is None
    assert info.developer_mode is False
    assert info.mac is None


def test_standby_and_missing_name() -> None:
    info = DeviceInfo.from_api({"device": {"PowerState": "standby"}})

    assert info.power_on is False
    assert info.name == "Samsung TV"


def test_frame_flag() -> None:
    frame = DeviceInfo.from_api({"device": {"FrameTVSupport": "true"}})
    assert frame.frame_tv is True
    assert DeviceInfo.from_api({"device": {}}).frame_tv is False
