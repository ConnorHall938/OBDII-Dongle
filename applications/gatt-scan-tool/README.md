# BLE GATT Scan Tool

A tkinter desktop app for poking at Bluetooth LE GATT devices: scan, connect,
browse services, read/write characteristics, and subscribe to notifications.
Works with any BLE peripheral; a second tab is wired to the `CAN-BLE` firmware
in [`../port`](../port) for live RPM/Speed.

## Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Requires Python 3.10+ with tkinter (`dnf install python3-tkinter` on Fedora if
missing) and a running BlueZ stack (`systemctl status bluetooth`). The only
dependency is [bleak](https://github.com/hbldh/bleak) 3.x.

## Run

```bash
.venv/bin/python -m gatt_tool
```

No root needed — BlueZ lets the logged-in session user scan and connect.

## GATT Explorer tab

Generic, works with any peripheral.

- **Scan** — live results with RSSI, updating as devices are heard. Filter by
  name substring, hide unnamed devices, or narrow to just things advertising
  the OBD service UUID. Double-click a row to connect.
- **Services** — the full service → characteristic → descriptor tree. Known
  UUIDs get friendly names; a `●` marks characteristics you're subscribed to.
- **Value** — `Read` a characteristic and every plausible decode is listed at
  once (hex, u8/u16/u32 in both endiannesses, signed, float, ascii, utf-8), so
  you don't have to guess the format up front. Write by picking a format and
  typing a value; `Notify` subscribes. Buttons enable/disable from the
  characteristic's actual properties, and you can subscribe to several at once.
- **Log** — timestamped, colour-coded TX/RX, saveable to a file.

## CAN-BLE Dashboard tab

Bound to the UUIDs in [`../port/src/bt`](../port/src/bt):

| | UUID | Format |
|---|---|---|
| OBD service | `d50d4d4d-0f37-41c7-a089-9c6b8e490640` | — |
| RPM | `7e86f3ad-db47-4281-8993-f791eab26719` | uint16 LE, read + notify |
| Speed | `3228dd8f-90b6-41f0-a991-bf7d18306881` | uint8, read + notify |
| NUS | `6e400001/2/3-b5a3-f393-e0a9-e50e24dcca9e` | Zephyr NUS (Nordic UUIDs) |

`Connect to CAN-BLE` scans by name, connects, and subscribes to RPM, Speed and
NUS TX automatically. You get large live readouts, a rolling 60-second strip
chart, a serial console over NUS, and `Record CSV…` to capture
`time,signal,value` rows for later analysis.

If you connect to a device without these characteristics, the tab says which
ones are missing rather than erroring — the Explorer tab still works normally.

## How it works

bleak is asyncio and tkinter has its own event loop, so they never share a
thread:

- `ble.BleWorker` runs an asyncio loop on a daemon thread and owns every bleak
  object. Its public methods are safe to call from the GUI thread; they queue
  work and return immediately.
- Results come back as plain dataclass events on a `queue.Queue`, drained by
  `root.after()` in `app.py` (capped per tick so a chatty notifier can't starve
  the UI) and handed to both tabs.
- The worker flattens `client.services` into inert `ServiceInfo`/`CharInfo`
  dataclasses. The GUI addresses characteristics by integer **handle** — UUIDs
  can repeat within a device, handles can't.

Notes for anyone extending it: scanning is **active**, because CAN-BLE puts its
name in the scan response rather than the advertising payload. Never write the
CCCD (`0x2902`) directly — bleak 3.0 raises `ValueError`; use
`start_notify`/`stop_notify`, which handles it.

## Files

| File | |
|---|---|
| `gatt_tool/ble.py` | asyncio worker thread, event types, GATT snapshotting |
| `gatt_tool/app.py` | root window, notebook, event pump |
| `gatt_tool/explorer.py` | GATT Explorer tab |
| `gatt_tool/dashboard.py` | CAN-BLE dashboard tab |
| `gatt_tool/codec.py` | value decode/encode helpers |
| `gatt_tool/uuids.py` | UUID → friendly name table |
