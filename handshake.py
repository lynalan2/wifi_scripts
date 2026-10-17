#!/usr/bin/env python3
"""Совместимость: код переехал в wifitool.netscan / wifitool.capture."""
from wifitool.capture import handshake_flow, capture_handshake, check_handshake
from wifitool.netscan import scan_networks, display_networks

__all__ = [
    "handshake_flow", "capture_handshake", "check_handshake",
    "scan_networks", "display_networks",
]
