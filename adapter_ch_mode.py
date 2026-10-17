#!/usr/bin/env python3
"""Совместимость: функции переехали в wifitool.iface."""

from wifitool.iface import (
    get_interface_mode,
    get_interface_phy,
    interface_exists,
    set_monitor_mode,
    set_managed_mode,
)

__all__ = [
    "get_interface_mode", "get_interface_phy", "interface_exists",
    "set_monitor_mode", "set_managed_mode",
]
