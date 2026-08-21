"""Root window: owns the BLE worker and pumps its events into both tabs."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from . import ble
from .dashboard import DashboardTab
from .explorer import ExplorerTab

PUMP_MS = 50
MAX_EVENTS_PER_PUMP = 200  # keeps a chatty notifier from starving the UI


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BLE GATT Scan Tool")
        self.geometry("1180x800")
        self.minsize(900, 620)

        self.worker = ble.BleWorker()
        self.worker.start()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self.explorer = ExplorerTab(notebook, self.worker)
        self.dashboard = DashboardTab(notebook, self.worker)
        notebook.add(self.explorer, text="GATT Explorer")
        notebook.add(self.dashboard, text="CAN-BLE Dashboard")

        self.status = ttk.Label(self, text="Ready", anchor="w", relief="sunken", padding=(6, 2))
        self.status.pack(fill="x", side="bottom")

        self._notifications = 0
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(PUMP_MS, self._pump)

    # Both tabs see every event; each ignores what it doesn't care about.
    def _pump(self) -> None:
        for _ in range(MAX_EVENTS_PER_PUMP):
            try:
                event = self.worker.events.get_nowait()
            except queue.Empty:
                break
            self._update_status(event)
            for tab in (self.explorer, self.dashboard):
                try:
                    tab.handle_event(event)
                except Exception as exc:  # a UI bug must not kill the pump
                    self.explorer.log(f"UI error handling {type(event).__name__}: {exc}", "err")
        self.after(PUMP_MS, self._pump)

    def _update_status(self, event: ble.Event) -> None:
        match event:
            case ble.Connected():
                self._notifications = 0
                self.status.configure(
                    text=f"Connected — {event.name} [{event.address}] · MTU {event.mtu}"
                )
            case ble.Disconnected():
                self.status.configure(text="Disconnected")
            case ble.ScanState():
                if event.scanning:
                    self.status.configure(text="Scanning…")
                elif not self.worker.is_connected:
                    self.status.configure(text="Ready")
            case ble.Notification():
                self._notifications += 1
                if self._notifications % 10 == 0 or self._notifications < 10:
                    base = self.status.cget("text").split(" · notif")[0]
                    self.status.configure(text=f"{base} · notif {self._notifications}")
            case ble.Error():
                self.status.configure(text=f"Error [{event.context}]: {event.message}")

    def _on_close(self) -> None:
        self.dashboard.close()
        self.worker.shutdown()
        self.destroy()


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
