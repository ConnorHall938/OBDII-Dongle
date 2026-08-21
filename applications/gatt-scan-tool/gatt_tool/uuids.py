"""UUID -> human readable name lookup.

Covers the handful of SIG-assigned UUIDs you actually run into plus the
custom UUIDs from the CAN-BLE firmware in ../port.
"""

from __future__ import annotations

# --- CAN-BLE (applications/port/src/bt/bt_obd/bt_obd.c) ---
OBD_SERVICE = "d50d4d4d-0f37-41c7-a089-9c6b8e490640"
OBD_RPM = "7e86f3ad-db47-4281-8993-f791eab26719"
OBD_SPEED = "3228dd8f-90b6-41f0-a991-bf7d18306881"

# --- Nordic UART Service, as used by Zephyr's CONFIG_BT_ZEPHYR_NUS ---
NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # client writes here
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # peripheral notifies here

DEVICE_NAME = "CAN-BLE"

_NAMES: dict[str, str] = {
    # CAN-BLE
    OBD_SERVICE: "OBD Service",
    OBD_RPM: "RPM",
    OBD_SPEED: "Speed",
    NUS_SERVICE: "Nordic UART Service",
    NUS_RX: "NUS RX (write)",
    NUS_TX: "NUS TX (notify)",
    # SIG services
    "00001800-0000-1000-8000-00805f9b34fb": "Generic Access",
    "00001801-0000-1000-8000-00805f9b34fb": "Generic Attribute",
    "0000180a-0000-1000-8000-00805f9b34fb": "Device Information",
    "0000180f-0000-1000-8000-00805f9b34fb": "Battery Service",
    "0000181c-0000-1000-8000-00805f9b34fb": "User Data",
    "0000fe59-0000-1000-8000-00805f9b34fb": "Nordic DFU",
    # SIG characteristics
    "00002a00-0000-1000-8000-00805f9b34fb": "Device Name",
    "00002a01-0000-1000-8000-00805f9b34fb": "Appearance",
    "00002a04-0000-1000-8000-00805f9b34fb": "Preferred Connection Parameters",
    "00002a05-0000-1000-8000-00805f9b34fb": "Service Changed",
    "00002a19-0000-1000-8000-00805f9b34fb": "Battery Level",
    "00002a23-0000-1000-8000-00805f9b34fb": "System ID",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00002a25-0000-1000-8000-00805f9b34fb": "Serial Number",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Revision",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware Revision",
    "00002a28-0000-1000-8000-00805f9b34fb": "Software Revision",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer Name",
    "00002aa6-0000-1000-8000-00805f9b34fb": "Central Address Resolution",
    # SIG descriptors
    "00002900-0000-1000-8000-00805f9b34fb": "Characteristic Extended Properties",
    "00002901-0000-1000-8000-00805f9b34fb": "Characteristic User Description",
    "00002902-0000-1000-8000-00805f9b34fb": "Client Characteristic Configuration",
    "00002903-0000-1000-8000-00805f9b34fb": "Server Characteristic Configuration",
    "00002904-0000-1000-8000-00805f9b34fb": "Characteristic Presentation Format",
}


def name_for(uuid: str, fallback: str = "") -> str:
    """Friendly name for a UUID, falling back to bleak's description then the UUID."""
    known = _NAMES.get(uuid.lower())
    if known:
        return known
    if fallback and fallback.lower() != "unknown":
        return fallback
    return short(uuid)


def short(uuid: str) -> str:
    """`0000180f-0000-...-...` -> `0x180F`; custom 128-bit UUIDs pass through."""
    u = uuid.lower()
    if u.startswith("0000") and u.endswith("-0000-1000-8000-00805f9b34fb"):
        return f"0x{u[4:8].upper()}"
    return uuid
