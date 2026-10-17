#!/usr/bin/env python3
"""Совместимость: функции переехали в wifitool.iface."""

from wifitool.iface import (
    list_wifi_interfaces,
    get_wifi_info,
    get_name_mac_type_adapters,
)

__all__ = ["list_wifi_interfaces", "get_wifi_info", "get_name_mac_type_adapters"]
