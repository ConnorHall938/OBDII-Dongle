"""BLE plumbing: an asyncio event loop on its own thread, talking to tkinter
through a queue.

bleak is asyncio and tkinter has its own event loop, so the two never share a
thread here. Every bleak object lives on the worker thread; the GUI only ever
sees the plain dataclasses below, and refers to characteristics by their
integer handle (unique per connection, unlike the UUID, which can repeat).
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError

# ---------------------------------------------------------------- GATT model


@dataclass(frozen=True)
class DescInfo:
    handle: int
    uuid: str
    description: str


@dataclass(frozen=True)
class CharInfo:
    handle: int
    uuid: str
    description: str
    properties: tuple[str, ...]
    descriptors: tuple[DescInfo, ...] = ()

    @property
    def readable(self) -> bool:
        return "read" in self.properties

    @property
    def writable(self) -> bool:
        return "write" in self.properties

    @property
    def writable_no_response(self) -> bool:
        return "write-without-response" in self.properties

    @property
    def notifiable(self) -> bool:
        return "notify" in self.properties or "indicate" in self.properties


@dataclass(frozen=True)
class ServiceInfo:
    handle: int
    uuid: str
    description: str
    characteristics: tuple[CharInfo, ...]


# -------------------------------------------------------------------- events


@dataclass
class ScanHit:
    address: str
    name: Optional[str]
    rssi: int
    service_uuids: tuple[str, ...]


@dataclass
class ScanState:
    scanning: bool


@dataclass
class Connected:
    address: str
    name: str
    mtu: int


@dataclass
class Disconnected:
    reason: str = ""


@dataclass
class ServicesDiscovered:
    services: tuple[ServiceInfo, ...]


@dataclass
class ReadResult:
    handle: int
    data: bytes


@dataclass
class WriteDone:
    handle: int
    length: int


@dataclass
class Notification:
    handle: int
    data: bytes
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class NotifyState:
    handle: int
    enabled: bool


@dataclass
class Error:
    context: str
    message: str


@dataclass
class Log:
    message: str


Event = (
    ScanHit | ScanState | Connected | Disconnected | ServicesDiscovered
    | ReadResult | WriteDone | Notification | NotifyState | Error | Log
)


# -------------------------------------------------------------------- worker


class BleWorker:
    """Owns the asyncio loop and all bleak state.

    Public methods are safe to call from the tkinter thread. They queue work
    and return immediately; every result arrives back as an event on `events`.
    """

    def __init__(self) -> None:
        self.events: queue.Queue[Event] = queue.Queue()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, name="ble", daemon=True)

        # Worker-thread state — never touch these from the GUI thread.
        self._scanner: Optional[BleakScanner] = None
        self._client: Optional[BleakClient] = None
        self._devices: dict[str, BLEDevice] = {}
        self._chars: dict[int, BleakGATTCharacteristic] = {}
        self._subscribed: set[int] = set()

        # Plain bool mirroring the link state, so the GUI can ask without
        # reaching into a BleakClient from the wrong thread.
        self._connected = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def shutdown(self) -> None:
        """Stop scanning, drop the connection, stop the loop. Blocks briefly."""
        if self._loop is None or not self._loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            future.result(timeout=5.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2.0)

    async def _shutdown(self) -> None:
        await self._stop_scan()
        await self._disconnect()

    # -- dispatch ----------------------------------------------------------

    def _emit(self, event: Event) -> None:
        self.events.put(event)

    def _submit(self, coro_fn: Callable[[], Any], context: str) -> None:
        """Run a coroutine on the worker loop, reporting failures as events."""
        if self._loop is None or not self._loop.is_running():
            self._emit(Error(context, "BLE worker is not running"))
            return

        async def guarded() -> None:
            try:
                await coro_fn()
            except asyncio.CancelledError:
                raise
            except BleakError as exc:
                self._emit(Error(context, str(exc) or exc.__class__.__name__))
            except Exception as exc:  # noqa: BLE001 - surface everything to the UI
                self._emit(Error(context, f"{exc.__class__.__name__}: {exc}"))

        asyncio.run_coroutine_threadsafe(guarded(), self._loop)

    # -- scanning ----------------------------------------------------------

    def start_scan(self, service_uuids: Optional[list[str]] = None) -> None:
        self._submit(lambda: self._start_scan(service_uuids), "scan")

    def stop_scan(self) -> None:
        self._submit(self._stop_scan, "scan")

    async def _start_scan(self, service_uuids: Optional[list[str]]) -> None:
        await self._stop_scan()
        self._devices.clear()

        def detected(device: BLEDevice, adv: AdvertisementData) -> None:
            self._devices[device.address] = device
            self._emit(
                ScanHit(
                    address=device.address,
                    name=adv.local_name or device.name,
                    rssi=adv.rssi,  # BLEDevice.rssi was removed in bleak 1.0
                    service_uuids=tuple(adv.service_uuids),
                )
            )

        # Active scanning: CAN-BLE puts its name in the scan response, which a
        # passive scan never asks for.
        self._scanner = BleakScanner(
            detection_callback=detected,
            service_uuids=service_uuids or None,
            scanning_mode="active",
        )
        await self._scanner.start()
        self._emit(ScanState(True))

    async def _stop_scan(self) -> None:
        if self._scanner is None:
            return
        scanner, self._scanner = self._scanner, None
        try:
            await scanner.stop()
        except BleakError:
            pass
        self._emit(ScanState(False))

    # -- connection --------------------------------------------------------

    def connect(self, address: str) -> None:
        self._submit(lambda: self._connect(address), "connect")

    def disconnect(self) -> None:
        self._submit(self._disconnect, "disconnect")

    def connect_by_name(self, name: str, timeout: float = 10.0) -> None:
        """Scan for a device by exact name, then connect to it."""
        self._submit(lambda: self._connect_by_name(name, timeout), "connect")

    async def _connect_by_name(self, name: str, timeout: float) -> None:
        self._emit(Log(f"Looking for {name!r}…"))
        device = await BleakScanner.find_device_by_name(
            name, timeout=timeout, scanning_mode="active"
        )
        if device is None:
            self._emit(Error("connect", f"No device named {name!r} found in {timeout:g}s"))
            return
        self._devices[device.address] = device
        await self._connect(device.address)

    async def _connect(self, address: str) -> None:
        await self._stop_scan()
        await self._disconnect()

        # Prefer the BLEDevice from the scan — BlueZ connects more reliably
        # with it than with a bare address string.
        target: BLEDevice | str = self._devices.get(address, address)
        self._emit(Log(f"Connecting to {address}…"))

        def on_disconnect(_client: BleakClient) -> None:
            self._connected = False
            self._chars.clear()
            self._subscribed.clear()
            self._emit(Disconnected("link lost"))

        client = BleakClient(target, disconnected_callback=on_disconnect, timeout=30)
        await client.connect()
        self._client = client
        self._connected = True

        services = self._snapshot_services(client)
        self._emit(Connected(client.address, client.name or "(unnamed)", client.mtu_size))
        self._emit(ServicesDiscovered(services))

    def _snapshot_services(self, client: BleakClient) -> tuple[ServiceInfo, ...]:
        """Flatten bleak's live objects into inert dataclasses for the GUI."""
        self._chars.clear()
        out: list[ServiceInfo] = []
        for service in client.services:
            chars: list[CharInfo] = []
            for char in service.characteristics:
                self._chars[char.handle] = char
                chars.append(
                    CharInfo(
                        handle=char.handle,
                        uuid=char.uuid,
                        description=char.description,
                        properties=tuple(char.properties),
                        descriptors=tuple(
                            DescInfo(d.handle, d.uuid, d.description)
                            for d in char.descriptors
                        ),
                    )
                )
            out.append(
                ServiceInfo(
                    handle=service.handle,
                    uuid=service.uuid,
                    description=service.description,
                    characteristics=tuple(chars),
                )
            )
        return tuple(out)

    async def _disconnect(self) -> None:
        if self._client is None:
            return
        client, self._client = self._client, None
        self._connected = False
        self._chars.clear()
        self._subscribed.clear()
        try:
            if client.is_connected:
                await client.disconnect()
        except BleakError:
            pass
        self._emit(Disconnected())

    @property
    def is_connected(self) -> bool:
        """Safe to read from the GUI thread — a plain bool, not a bleak call."""
        return self._connected

    # -- GATT operations ---------------------------------------------------

    def read(self, handle: int) -> None:
        self._submit(lambda: self._read(handle), "read")

    async def _read(self, handle: int) -> None:
        client, char = self._require(handle)
        data = bytes(await client.read_gatt_char(char))
        self._emit(ReadResult(handle, data))

    def write(self, handle: int, data: bytes, response: bool = True) -> None:
        self._submit(lambda: self._write(handle, data, response), "write")

    async def _write(self, handle: int, data: bytes, response: bool) -> None:
        client, char = self._require(handle)
        await client.write_gatt_char(char, data, response=response)
        self._emit(WriteDone(handle, len(data)))

    def read_descriptor(self, handle: int) -> None:
        self._submit(lambda: self._read_descriptor(handle), "read")

    async def _read_descriptor(self, handle: int) -> None:
        if self._client is None:
            raise BleakError("not connected")
        data = bytes(await self._client.read_gatt_descriptor(handle))
        self._emit(ReadResult(handle, data))

    def set_notify(self, handle: int, enabled: bool) -> None:
        self._submit(lambda: self._set_notify(handle, enabled), "notify")

    async def _set_notify(self, handle: int, enabled: bool) -> None:
        client, char = self._require(handle)

        if enabled:
            if handle in self._subscribed:
                return

            def on_notify(sender: BleakGATTCharacteristic, data: bytearray) -> None:
                self._emit(Notification(sender.handle, bytes(data)))

            # start_notify writes the CCCD for us; writing 0x2902 by hand
            # raises ValueError in bleak 3.0.
            await client.start_notify(char, on_notify)
            self._subscribed.add(handle)
        else:
            if handle not in self._subscribed:
                return
            await client.stop_notify(char)
            self._subscribed.discard(handle)

        self._emit(NotifyState(handle, enabled))

    def _require(self, handle: int) -> tuple[BleakClient, BleakGATTCharacteristic]:
        client = self._client
        if client is None or not client.is_connected:
            raise BleakError("not connected")
        char = self._chars.get(handle)
        if char is None:
            raise BleakError(f"characteristic handle {handle} not found")
        return client, char
