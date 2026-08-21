"""A tkinter GUI for exploring Bluetooth LE GATT devices."""

__all__ = ["main"]


def main() -> None:
    from .app import main as _main

    _main()
