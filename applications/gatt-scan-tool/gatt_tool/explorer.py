"""Tab 1: a general-purpose GATT explorer that works with any peripheral."""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from . import ble, codec, uuids

MAX_LOG_LINES = 2000
MONO = ("TkFixedFont", 10)


class ExplorerTab(ttk.Frame):
    def __init__(self, master: tk.Misc, worker: ble.BleWorker) -> None:
        super().__init__(master, padding=6)
        self.worker = worker

        self._chars: dict[int, ble.CharInfo] = {}
        self._char_rows: dict[int, str] = {}  # handle -> treeview item id
        self._subscribed: set[int] = set()
        self._selected: Optional[int] = None
        self._selected_is_desc = False
        self._scanning = False
        self._connected = False  # driven by events, never by asking bleak
        self._seen: dict[str, dict] = {}

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)
        panes.add(self._build_scan_pane(panes), weight=1)
        panes.add(self._build_gatt_pane(panes), weight=2)

        self._update_action_states()

    # ------------------------------------------------------------ left pane

    def _build_scan_pane(self, master: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(master, padding=(0, 0, 6, 0))

        controls = ttk.LabelFrame(frame, text="Scan", padding=6)
        controls.pack(fill="x")

        row = ttk.Frame(controls)
        row.pack(fill="x")
        self.scan_button = ttk.Button(row, text="Start scan", command=self._toggle_scan)
        self.scan_button.pack(side="left")
        ttk.Button(row, text="Clear", command=self._clear_devices).pack(side="left", padx=4)

        filt = ttk.Frame(controls)
        filt.pack(fill="x", pady=(6, 0))
        ttk.Label(filt, text="Name contains:").pack(side="left")
        self.name_filter = tk.StringVar()
        self.name_filter.trace_add("write", lambda *_: self._refresh_devices())
        ttk.Entry(filt, textvariable=self.name_filter, width=14).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        self.named_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            controls, text="Named devices only", variable=self.named_only,
            command=self._refresh_devices,
        ).pack(anchor="w", pady=(4, 0))

        self.obd_only = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            controls, text="Only the OBD service", variable=self.obd_only,
            command=self._refresh_devices,
        ).pack(anchor="w")

        devices = ttk.LabelFrame(frame, text="Devices", padding=6)
        devices.pack(fill="both", expand=True, pady=(6, 0))

        self.device_tree = ttk.Treeview(
            devices, columns=("name", "address", "rssi"), show="headings",
            selectmode="browse",
        )
        for col, text, width, anchor in (
            ("name", "Name", 108, "w"),
            ("address", "Address", 118, "w"),
            ("rssi", "RSSI", 44, "e"),
        ):
            self.device_tree.heading(col, text=text)
            self.device_tree.column(col, width=width, anchor=anchor, stretch=(col == "name"))
        self.device_tree.pack(side="left", fill="both", expand=True)
        self.device_tree.bind("<Double-1>", lambda _e: self._connect_selected())
        self.device_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_action_states())

        bar = ttk.Scrollbar(devices, orient="vertical", command=self.device_tree.yview)
        bar.pack(side="right", fill="y")
        self.device_tree.configure(yscrollcommand=bar.set)

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(6, 0))
        self.connect_button = ttk.Button(buttons, text="Connect", command=self._connect_selected)
        self.connect_button.pack(side="left")
        self.disconnect_button = ttk.Button(
            buttons, text="Disconnect", command=self.worker.disconnect
        )
        self.disconnect_button.pack(side="left", padx=4)
        return frame

    # ----------------------------------------------------------- right pane

    def _build_gatt_pane(self, master: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(master)
        stack = ttk.PanedWindow(frame, orient="vertical")
        stack.pack(fill="both", expand=True)

        # --- GATT tree ---
        tree_frame = ttk.LabelFrame(stack, text="Services", padding=6)
        self.gatt_tree = ttk.Treeview(
            tree_frame, columns=("props", "uuid"), selectmode="browse", height=16
        )
        self.gatt_tree.heading("#0", text="Service / Characteristic")
        self.gatt_tree.heading("props", text="Properties")
        self.gatt_tree.heading("uuid", text="UUID")
        self.gatt_tree.column("#0", width=240, stretch=True)
        self.gatt_tree.column("props", width=180, stretch=False)
        self.gatt_tree.column("uuid", width=290, stretch=False)
        self.gatt_tree.pack(side="left", fill="both", expand=True)
        self.gatt_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_gatt_select())

        gatt_bar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.gatt_tree.yview)
        gatt_bar.pack(side="right", fill="y")
        self.gatt_tree.configure(yscrollcommand=gatt_bar.set)
        stack.add(tree_frame, weight=4)

        # --- value / actions ---
        value_frame = ttk.LabelFrame(stack, text="Value", padding=6)

        actions = ttk.Frame(value_frame)
        actions.pack(fill="x")
        self.read_button = ttk.Button(actions, text="Read", command=self._read_selected)
        self.read_button.pack(side="left")
        self.notify_var = tk.BooleanVar(value=False)
        self.notify_check = ttk.Checkbutton(
            actions, text="Notify", variable=self.notify_var, command=self._toggle_notify
        )
        self.notify_check.pack(side="left", padx=(8, 0))
        self.char_label = ttk.Label(actions, text="No characteristic selected")
        self.char_label.pack(side="left", padx=(12, 0))

        body = ttk.Frame(value_frame)
        body.pack(fill="both", expand=True, pady=(6, 0))
        self.value_text = tk.Text(body, height=6, width=44, font=MONO, wrap="none")
        self.value_text.pack(side="left", fill="both", expand=True)
        self.value_text.configure(state="disabled")
        value_bar = ttk.Scrollbar(body, orient="vertical", command=self.value_text.yview)
        value_bar.pack(side="right", fill="y")
        self.value_text.configure(yscrollcommand=value_bar.set)

        write = ttk.Frame(value_frame)
        write.pack(fill="x", pady=(6, 0))
        ttk.Label(write, text="Write:").pack(side="left")
        self.write_entry = ttk.Entry(write)
        self.write_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.write_entry.bind("<Return>", lambda _e: self._write_selected(True))
        self.write_format = ttk.Combobox(
            write, values=list(codec.WRITE_FORMATS), width=7, state="readonly"
        )
        self.write_format.set("hex")
        self.write_format.pack(side="left")
        self.write_button = ttk.Button(
            write, text="Write", command=lambda: self._write_selected(True)
        )
        self.write_button.pack(side="left", padx=4)
        self.write_nr_button = ttk.Button(
            write, text="Write (no resp)", command=lambda: self._write_selected(False)
        )
        self.write_nr_button.pack(side="left")
        stack.add(value_frame, weight=2)

        # --- log ---
        log_frame = ttk.LabelFrame(stack, text="Log", padding=6)
        log_top = ttk.Frame(log_frame)
        log_top.pack(fill="x")
        ttk.Button(log_top, text="Clear", command=self._clear_log).pack(side="left")
        ttk.Button(log_top, text="Save…", command=self._save_log).pack(side="left", padx=4)
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(log_top, text="Autoscroll", variable=self.autoscroll).pack(side="left")

        log_body = ttk.Frame(log_frame)
        log_body.pack(fill="both", expand=True, pady=(4, 0))
        self.log_text = tk.Text(log_body, height=6, font=MONO, wrap="none")
        self.log_text.pack(side="left", fill="both", expand=True)
        self.log_text.tag_configure("rx", foreground="#127a2a")
        self.log_text.tag_configure("tx", foreground="#1a4fbd")
        self.log_text.tag_configure("err", foreground="#b3261e")
        self.log_text.tag_configure("info", foreground="#555555")
        self.log_text.configure(state="disabled")

        log_bar = ttk.Scrollbar(log_body, orient="vertical", command=self.log_text.yview)
        log_bar.pack(side="right", fill="y")
        self.log_text.configure(yscrollcommand=log_bar.set)
        stack.add(log_frame, weight=2)
        return frame

    # -------------------------------------------------------------- logging

    def log(self, message: str, tag: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp}  {message}\n", tag)
        # Ring-buffer the log so a chatty notifier can't grow it without bound.
        excess = int(self.log_text.index("end-1c").split(".")[0]) - MAX_LOG_LINES
        if excess > 0:
            self.log_text.delete("1.0", f"{excess + 1}.0")
        if self.autoscroll.get():
            self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _save_log(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save log", defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self.log_text.get("1.0", "end-1c"))
        except OSError as exc:
            messagebox.showerror("Save log", str(exc))
            return
        self.log(f"Log saved to {path}")

    # ------------------------------------------------------------- scanning

    def _toggle_scan(self) -> None:
        if self._scanning:
            self.worker.stop_scan()
        else:
            self._clear_devices()
            self.worker.start_scan([uuids.OBD_SERVICE] if self.obd_only.get() else None)

    def _clear_devices(self) -> None:
        self._seen.clear()
        self.device_tree.delete(*self.device_tree.get_children())

    def _passes_filter(self, entry: dict) -> bool:
        name = entry["name"]
        if self.named_only.get() and not name:
            return False
        needle = self.name_filter.get().strip().lower()
        if needle and needle not in (name or "").lower():
            return False
        if self.obd_only.get() and uuids.OBD_SERVICE not in entry["service_uuids"]:
            return False
        return True

    def _refresh_devices(self) -> None:
        selected = self.device_tree.selection()
        keep = selected[0] if selected else None
        self.device_tree.delete(*self.device_tree.get_children())
        rows = sorted(self._seen.values(), key=lambda e: e["rssi"], reverse=True)
        for entry in rows:
            if not self._passes_filter(entry):
                continue
            self.device_tree.insert(
                "", "end", iid=entry["address"],
                values=(entry["name"] or "(unnamed)", entry["address"], entry["rssi"]),
            )
        if keep and self.device_tree.exists(keep):
            self.device_tree.selection_set(keep)
        self._update_action_states()

    def _connect_selected(self) -> None:
        selection = self.device_tree.selection()
        if not selection:
            return
        self.worker.connect(selection[0])

    # ---------------------------------------------------------- GATT browser

    def _on_gatt_select(self) -> None:
        selection = self.gatt_tree.selection()
        self._selected = None
        self._selected_is_desc = False
        if selection:
            item = selection[0]
            tags = self.gatt_tree.item(item, "tags")
            if "char" in tags or "desc" in tags:
                # iid is "<kind>:<handle>", possibly with a "#n" uniquifier.
                self._selected = int(item.split(":")[1].split("#")[0])
                self._selected_is_desc = "desc" in tags
        self._set_value_text("")
        self._update_action_states()

    def _update_action_states(self) -> None:
        connected = self._connected
        self.scan_button.configure(text="Stop scan" if self._scanning else "Start scan")
        self.connect_button.configure(
            state="normal" if self.device_tree.selection() and not connected else "disabled"
        )
        self.disconnect_button.configure(state="normal" if connected else "disabled")

        char = self._chars.get(self._selected) if self._selected is not None else None

        if self._selected_is_desc and self._selected is not None:
            self.char_label.configure(text=f"Descriptor handle {self._selected}")
            self.read_button.configure(state="normal" if connected else "disabled")
            self.notify_check.configure(state="disabled")
            self.write_button.configure(state="disabled")
            self.write_nr_button.configure(state="disabled")
            self.write_entry.configure(state="disabled")
            return

        self.write_entry.configure(state="normal")
        if char is None:
            self.char_label.configure(text="No characteristic selected")
            for widget in (self.read_button, self.notify_check,
                           self.write_button, self.write_nr_button):
                widget.configure(state="disabled")
            self.notify_var.set(False)
            return

        name = uuids.name_for(char.uuid, char.description)
        self.char_label.configure(text=f"{name}  ·  handle {char.handle}")
        self.read_button.configure(state="normal" if connected and char.readable else "disabled")
        self.notify_check.configure(
            state="normal" if connected and char.notifiable else "disabled"
        )
        self.write_button.configure(state="normal" if connected and char.writable else "disabled")
        self.write_nr_button.configure(
            state="normal" if connected and char.writable_no_response else "disabled"
        )
        self.notify_var.set(char.handle in self._subscribed)

    def _set_value_text(self, text: str) -> None:
        self.value_text.configure(state="normal")
        self.value_text.delete("1.0", "end")
        self.value_text.insert("1.0", text)
        self.value_text.configure(state="disabled")

    def _read_selected(self) -> None:
        if self._selected is None:
            return
        if self._selected_is_desc:
            self.worker.read_descriptor(self._selected)
        else:
            self.worker.read(self._selected)

    def _write_selected(self, response: bool) -> None:
        if self._selected is None or self._selected_is_desc:
            return
        try:
            data = codec.encode(self.write_entry.get(), self.write_format.get())
        except ValueError as exc:
            self.log(f"Write rejected: {exc}", "err")
            return
        self.worker.write(self._selected, data, response=response)
        kind = "write" if response else "write-no-resp"
        self.log(f"TX {self._label(self._selected)} {kind}: {codec.hexdump(data)}", "tx")

    def _toggle_notify(self) -> None:
        if self._selected is None or self._selected_is_desc:
            return
        self.worker.set_notify(self._selected, self.notify_var.get())

    def _label(self, handle: int) -> str:
        char = self._chars.get(handle)
        if char is None:
            return f"handle {handle}"
        return uuids.name_for(char.uuid, char.description)

    def _mark_row(self, handle: int) -> None:
        """Put a bullet on subscribed characteristics in the tree."""
        item = self._char_rows.get(handle)
        char = self._chars.get(handle)
        if not item or char is None or not self.gatt_tree.exists(item):
            return
        prefix = "● " if handle in self._subscribed else ""
        self.gatt_tree.item(item, text=f"{prefix}{uuids.name_for(char.uuid, char.description)}")

    # --------------------------------------------------------- event intake

    def handle_event(self, event: ble.Event) -> None:
        match event:
            case ble.ScanHit():
                entry = {
                    "address": event.address, "name": event.name,
                    "rssi": event.rssi, "service_uuids": event.service_uuids,
                }
                known = self._seen.get(event.address)
                self._seen[event.address] = entry
                # Cheap path: an already-visible device just moved its RSSI.
                if (known and known["name"] == entry["name"]
                        and self.device_tree.exists(event.address)):
                    # str() so this column matches what the insert path writes.
                    self.device_tree.set(event.address, "rssi", str(event.rssi))
                else:
                    self._refresh_devices()

            case ble.ScanState():
                self._scanning = event.scanning
                self.log("Scanning…" if event.scanning else "Scan stopped")
                self._update_action_states()

            case ble.Connected():
                self._connected = True
                self.log(f"Connected to {event.name} [{event.address}], MTU {event.mtu}")
                self._update_action_states()

            case ble.Disconnected():
                self._connected = False
                self._subscribed.clear()
                self._chars.clear()
                self._char_rows.clear()
                self.gatt_tree.delete(*self.gatt_tree.get_children())
                self._selected = None
                self.log(f"Disconnected{f' ({event.reason})' if event.reason else ''}")
                self._update_action_states()

            case ble.ServicesDiscovered():
                self._populate_gatt(event.services)

            case ble.ReadResult():
                self._show_value(event.handle, event.data, "Read")

            case ble.WriteDone():
                self.log(f"Wrote {event.length} bytes to {self._label(event.handle)}", "tx")

            case ble.Notification():
                self._show_value(event.handle, event.data, "Notify")
                self.log(
                    f"RX {self._label(event.handle)}: {codec.hexdump(event.data)}", "rx"
                )

            case ble.NotifyState():
                if event.enabled:
                    self._subscribed.add(event.handle)
                else:
                    self._subscribed.discard(event.handle)
                self._mark_row(event.handle)
                state = "enabled" if event.enabled else "disabled"
                self.log(f"Notifications {state} on {self._label(event.handle)}")
                self._update_action_states()

            case ble.Error():
                self.log(f"[{event.context}] {event.message}", "err")
                self._update_action_states()

            case ble.Log():
                self.log(event.message)

    def _unique_iid(self, prefix: str, handle: int) -> str:
        """Tree ids must be unique. A peripheral reporting a duplicate handle
        shouldn't abort the whole insert and leave a half-built tree."""
        iid = f"{prefix}:{handle}"
        if not self.gatt_tree.exists(iid):
            return iid
        suffix = 1
        while self.gatt_tree.exists(f"{iid}#{suffix}"):
            suffix += 1
        return f"{iid}#{suffix}"

    def _populate_gatt(self, services: tuple[ble.ServiceInfo, ...]) -> None:
        self.gatt_tree.delete(*self.gatt_tree.get_children())
        self._chars.clear()
        self._char_rows.clear()

        for service in services:
            node = self.gatt_tree.insert(
                "", "end", iid=self._unique_iid("svc", service.handle),
                text=uuids.name_for(service.uuid, service.description),
                values=("", uuids.short(service.uuid)), open=True, tags=("svc",),
            )
            for char in service.characteristics:
                self._chars[char.handle] = char
                item = self.gatt_tree.insert(
                    node, "end", iid=self._unique_iid("chr", char.handle),
                    text=uuids.name_for(char.uuid, char.description),
                    values=(", ".join(char.properties), uuids.short(char.uuid)),
                    tags=("char",),
                )
                self._char_rows[char.handle] = item
                for desc in char.descriptors:
                    self.gatt_tree.insert(
                        item, "end", iid=self._unique_iid("dsc", desc.handle),
                        text=uuids.name_for(desc.uuid, desc.description),
                        values=("descriptor", uuids.short(desc.uuid)), tags=("desc",),
                    )
        count = sum(len(s.characteristics) for s in services)
        self.log(f"Discovered {len(services)} services, {count} characteristics")

    def _show_value(self, handle: int, data: bytes, source: str) -> None:
        if handle != self._selected:
            return
        lines = [f"{source}  ({time.strftime('%H:%M:%S')})"]
        width = max((len(label) for label, _ in codec.interpretations(data)), default=6)
        for label, value in codec.interpretations(data):
            lines.append(f"  {label:<{width}}  {value}")
        self._set_value_text("\n".join(lines))
