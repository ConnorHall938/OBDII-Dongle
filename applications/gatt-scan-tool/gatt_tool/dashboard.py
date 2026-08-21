"""Tab 2: a CAN-BLE specific view — RPM/Speed readouts, strip chart, NUS
console and CSV capture, wired to the UUIDs from ../port."""

from __future__ import annotations

import csv
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import ble, codec, uuids

WINDOW_SECONDS = 60.0
REDRAW_MS = 100  # 10 Hz
MONO = ("TkFixedFont", 10)

RPM_COLOR = "#1a4fbd"
SPEED_COLOR = "#127a2a"
GRID_COLOR = "#d8d8d8"
AXIS_COLOR = "#909090"


class Trace:
    """A rolling window of (timestamp, value) samples for one signal."""

    def __init__(self, label: str, unit: str, color: str, fmt: str) -> None:
        self.label = label
        self.unit = unit
        self.color = color
        self.fmt = fmt
        self.samples: deque[tuple[float, float]] = deque()
        self.handle: Optional[int] = None
        self.latest: Optional[float] = None

    def add(self, timestamp: float, value: float) -> None:
        self.latest = value
        self.samples.append((timestamp, value))
        self.trim(timestamp)

    def trim(self, now: float) -> None:
        cutoff = now - WINDOW_SECONDS
        while self.samples and self.samples[0][0] < cutoff:
            self.samples.popleft()

    def reset(self) -> None:
        self.samples.clear()
        self.latest = None
        self.handle = None


class DashboardTab(ttk.Frame):
    def __init__(self, master: tk.Misc, worker: ble.BleWorker) -> None:
        super().__init__(master, padding=6)
        self.worker = worker

        self.rpm = Trace("RPM", "rpm", RPM_COLOR, "u16le")
        self.speed = Trace("Speed", "km/h", SPEED_COLOR, "u8")
        self.traces = (self.rpm, self.speed)

        self._nus_tx: Optional[int] = None  # notify handle
        self._nus_rx: Optional[int] = None  # write handle
        self._connected = False
        self._csv_file = None
        self._csv_writer: Optional[csv.writer] = None

        self._build()
        self.after(REDRAW_MS, self._tick)

    # ---------------------------------------------------------------- layout

    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.connect_button = ttk.Button(
            top, text=f"Connect to {uuids.DEVICE_NAME}", command=self._connect
        )
        self.connect_button.pack(side="left")
        self.disconnect_button = ttk.Button(
            top, text="Disconnect", command=self.worker.disconnect, state="disabled"
        )
        self.disconnect_button.pack(side="left", padx=4)
        self.record_button = ttk.Button(
            top, text="Record CSV…", command=self._toggle_record, state="disabled"
        )
        self.record_button.pack(side="left", padx=(12, 0))
        self.status = ttk.Label(top, text="Not connected")
        self.status.pack(side="left", padx=12)

        readouts = ttk.Frame(self)
        readouts.pack(fill="x", pady=(8, 0))
        self.rpm_value = self._readout(readouts, "RPM", RPM_COLOR)
        self.speed_value = self._readout(readouts, "SPEED  (km/h)", SPEED_COLOR)

        chart_frame = ttk.LabelFrame(self, text=f"Last {WINDOW_SECONDS:g}s", padding=4)
        chart_frame.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas = tk.Canvas(chart_frame, height=240, background="white",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        nus = ttk.LabelFrame(self, text="NUS console", padding=6)
        nus.pack(fill="both", expand=True, pady=(8, 0))

        # Pack the entry row first with side="bottom" so a short window steals
        # height from the console, never from the controls.
        entry_row = ttk.Frame(nus)
        entry_row.pack(side="bottom", fill="x", pady=(4, 0))

        body = ttk.Frame(nus)
        body.pack(fill="both", expand=True)
        self.console = tk.Text(body, height=5, font=MONO, wrap="char")
        self.console.pack(side="left", fill="both", expand=True)
        self.console.tag_configure("rx", foreground=SPEED_COLOR)
        self.console.tag_configure("tx", foreground=RPM_COLOR)
        self.console.tag_configure("err", foreground="#b3261e")
        self.console.configure(state="disabled")
        bar = ttk.Scrollbar(body, orient="vertical", command=self.console.yview)
        bar.pack(side="right", fill="y")
        self.console.configure(yscrollcommand=bar.set)

        self.nus_entry = ttk.Entry(entry_row)
        self.nus_entry.pack(side="left", fill="x", expand=True)
        self.nus_entry.bind("<Return>", lambda _e: self._send_nus())
        self.append_newline = tk.BooleanVar(value=True)
        ttk.Checkbutton(entry_row, text="+\\n", variable=self.append_newline).pack(
            side="left", padx=4
        )
        self.hex_view = tk.BooleanVar(value=False)
        ttk.Checkbutton(entry_row, text="hex view", variable=self.hex_view).pack(side="left")
        self.send_button = ttk.Button(
            entry_row, text="Send", command=self._send_nus, state="disabled"
        )
        self.send_button.pack(side="left", padx=4)

    def _readout(self, master: tk.Misc, title: str, color: str) -> ttk.Label:
        box = ttk.Frame(master, padding=(0, 0, 24, 0))
        box.pack(side="left")
        ttk.Label(box, text=title, foreground=color).pack(anchor="w")
        value = ttk.Label(box, text="—", font=("TkDefaultFont", 30, "bold"),
                          foreground=color)
        value.pack(anchor="w")
        return value

    # ------------------------------------------------------------ connecting

    def _connect(self) -> None:
        self._log(f"Scanning for {uuids.DEVICE_NAME}…")
        self.worker.connect_by_name(uuids.DEVICE_NAME)

    def _bind_characteristics(self, services: tuple[ble.ServiceInfo, ...]) -> None:
        """Locate the CAN-BLE characteristics, if this device has them."""
        by_uuid = {
            char.uuid.lower(): char
            for service in services
            for char in service.characteristics
        }
        self.rpm.handle = self._handle_of(by_uuid, uuids.OBD_RPM)
        self.speed.handle = self._handle_of(by_uuid, uuids.OBD_SPEED)
        self._nus_tx = self._handle_of(by_uuid, uuids.NUS_TX)
        self._nus_rx = self._handle_of(by_uuid, uuids.NUS_RX)

        missing = [
            label for label, handle in (
                ("RPM", self.rpm.handle), ("Speed", self.speed.handle),
                ("NUS", self._nus_tx),
            ) if handle is None
        ]
        if missing:
            self._log(f"Not found on this device: {', '.join(missing)}", "err")

        for handle in (self.rpm.handle, self.speed.handle, self._nus_tx):
            if handle is not None:
                self.worker.set_notify(handle, True)
        for trace in self.traces:
            if trace.handle is not None:
                self.worker.read(trace.handle)

        self.send_button.configure(state="normal" if self._nus_rx is not None else "disabled")
        found = sum(1 for t in self.traces if t.handle is not None)
        self.status.configure(text=f"Connected · {found}/2 signals · subscribing")

    @staticmethod
    def _handle_of(by_uuid: dict[str, ble.CharInfo], uuid: str) -> Optional[int]:
        char = by_uuid.get(uuid.lower())
        return char.handle if char else None

    # --------------------------------------------------------- NUS console

    def _log(self, message: str, tag: str = "") -> None:
        self.console.configure(state="normal")
        self.console.insert("end", f"{time.strftime('%H:%M:%S')}  {message}\n", tag)
        excess = int(self.console.index("end-1c").split(".")[0]) - 1000
        if excess > 0:
            self.console.delete("1.0", f"{excess + 1}.0")
        self.console.see("end")
        self.console.configure(state="disabled")

    def _send_nus(self) -> None:
        if self._nus_rx is None:
            return
        text = self.nus_entry.get()
        if self.append_newline.get():
            text += "\n"
        data = text.encode("utf-8")
        # Zephyr's NUS RX is write-without-response; send it that way.
        self.worker.write(self._nus_rx, data, response=False)
        self._log(f"> {text.rstrip()}", "tx")
        self.nus_entry.delete(0, "end")

    # ------------------------------------------------------- CSV recording

    def _toggle_record(self) -> None:
        if self._csv_writer is not None:
            self._stop_record()
            return
        path = filedialog.asksaveasfilename(
            title="Record to CSV", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self._csv_file = open(path, "w", newline="", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Record CSV", str(exc))
            return
        self._csv_writer = csv.writer(self._csv_file)
        self._csv_writer.writerow(["time", "signal", "value"])
        self.record_button.configure(text="Stop recording")
        self._log(f"Recording to {path}")

    def _stop_record(self) -> None:
        if self._csv_file is not None:
            self._csv_file.close()
        self._csv_file = None
        self._csv_writer = None
        self.record_button.configure(text="Record CSV…")
        self._log("Recording stopped")

    def _record(self, signal: str, value: float) -> None:
        if self._csv_writer is None:
            return
        self._csv_writer.writerow([f"{time.time():.3f}", signal, value])

    # -------------------------------------------------------- event intake

    def handle_event(self, event: ble.Event) -> None:
        match event:
            case ble.Connected():
                self._connected = True
                self.connect_button.configure(state="disabled")
                self.disconnect_button.configure(state="normal")
                self.record_button.configure(state="normal")
                for trace in self.traces:
                    trace.reset()
                self._log(f"Connected to {event.name} [{event.address}], MTU {event.mtu}")

            case ble.ServicesDiscovered():
                self._bind_characteristics(event.services)

            case ble.Disconnected():
                self._connected = False
                self.connect_button.configure(state="normal")
                self.disconnect_button.configure(state="disabled")
                self.record_button.configure(state="disabled")
                self.send_button.configure(state="disabled")
                for trace in self.traces:
                    trace.handle = None
                self._nus_tx = self._nus_rx = None
                self.status.configure(text="Not connected")
                self._stop_record()
                self._log("Disconnected")

            case ble.Notification() | ble.ReadResult():
                self._on_value(event)

            case ble.NotifyState():
                if event.enabled and event.handle == self._nus_tx:
                    self.status.configure(text="Connected · streaming")

            case ble.Error():
                self._log(f"[{event.context}] {event.message}", "err")

            case ble.Log():
                self._log(event.message)

    def _on_value(self, event: ble.Notification | ble.ReadResult) -> None:
        if event.handle == self._nus_tx:
            if self.hex_view.get():
                self._log(f"< {codec.hexdump(event.data)}", "rx")
            else:
                text = event.data.decode("utf-8", errors="replace").rstrip("\r\n")
                self._log(f"< {text}", "rx")
            return

        # Notifications carry the instant the BLE thread saw them; a read has
        # no timestamp, so it lands at "now".
        arrived = getattr(event, "timestamp", None) or time.monotonic()
        for trace in self.traces:
            if trace.handle is None or event.handle != trace.handle:
                continue
            try:
                value = codec.decode_int(event.data, trace.fmt)
            except ValueError as exc:
                self._log(f"{trace.label}: {exc}", "err")
                return
            trace.add(arrived, value)
            self._record(trace.label, value)
            label = self.rpm_value if trace is self.rpm else self.speed_value
            label.configure(text=str(value))
            return

    # --------------------------------------------------------- strip chart

    def _tick(self) -> None:
        now = time.monotonic()
        for trace in self.traces:
            trace.trim(now)
        self._draw(now)
        self.after(REDRAW_MS, self._tick)

    def _draw(self, now: float) -> None:
        canvas = self.canvas
        canvas.delete("all")
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width < 60 or height < 60:
            return

        left, right = 52, width - 10
        top_pad, gap, bottom_pad = 8, 18, 16
        band = (height - top_pad - gap - bottom_pad) / 2

        for index, trace in enumerate(self.traces):
            top = top_pad + index * (band + gap)
            self._draw_band(trace, now, left, right, top, band)

        canvas.create_text(
            right, height - 3, anchor="se", fill=AXIS_COLOR,
            text=f"{WINDOW_SECONDS:g}s ago  →  now", font=("TkDefaultFont", 8),
        )

    def _draw_band(self, trace: Trace, now: float, left: int, right: int,
                   top: float, band: float) -> None:
        canvas = self.canvas
        bottom = top + band
        canvas.create_rectangle(left, top, right, bottom, outline=GRID_COLOR)
        # Series name inside the band — the gutter is reserved for numbers.
        canvas.create_text(
            left + 6, top + 3, anchor="nw", text=f"{trace.label} ({trace.unit})",
            fill=trace.color, font=("TkDefaultFont", 8),
        )

        if not trace.samples:
            canvas.create_text(
                (left + right) / 2, (top + bottom) / 2, text="no data",
                fill=AXIS_COLOR, font=("TkDefaultFont", 9),
            )
            return

        values = [value for _, value in trace.samples]
        low, high = min(values), max(values)
        if high - low < 1e-9:  # flat line — give it some room to sit in
            low, high = low - 1, high + 1
        span = high - low

        # Anchor the two gutter labels inward so neighbouring bands never touch.
        for value, y, anchor in ((high, top, "ne"), (low, bottom, "se")):
            canvas.create_line(left, y, right, y, fill=GRID_COLOR, dash=(2, 4))
            canvas.create_text(left - 5, y, anchor=anchor, text=f"{value:g}",
                               fill=AXIS_COLOR, font=("TkDefaultFont", 8))

        points: list[float] = []
        for timestamp, value in trace.samples:
            age = now - timestamp
            x = right - (age / WINDOW_SECONDS) * (right - left)
            y = bottom - ((value - low) / span) * band
            points.extend((max(left, x), y))

        if len(points) >= 4:
            canvas.create_line(*points, fill=trace.color, width=2)
        else:
            canvas.create_oval(points[0] - 2, points[1] - 2, points[0] + 2, points[1] + 2,
                               fill=trace.color, outline=trace.color)

    def close(self) -> None:
        self._stop_record()
