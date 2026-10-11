#!/usr/bin/env python3
"""
Функция перевода Wi-Fi адаптера в режим мониторинга.
Предполагается, что адаптер уже выбран и передан в функцию.
Требует: root, iw, ip.
"""

import re
import time
import subprocess


def get_interface_mode(interface):
    """Возвращает текущий тип интерфейса (managed, monitor, ...)."""
    r = subprocess.run(
        ["iw", "dev", interface, "info"],
        capture_output=True, text=True
    )
    m = re.search(r"type\s+(\w+)", r.stdout)
    return m.group(1) if m else "unknown"


def get_interface_phy(interface):
    """Возвращает имя phy (например, 'phy0') для интерфейса."""
    r = subprocess.run(
        ["iw", "dev", interface, "info"],
        capture_output=True, text=True
    )
    m = re.search(r"wiphy\s+(\d+)", r.stdout)
    return f"phy{m.group(1)}" if m else None


def interface_exists(interface):
    r = subprocess.run(
        ["iw", "dev", interface, "info"],
        capture_output=True, text=True
    )
    return r.returncode == 0


def set_monitor_mode(interface):
    """
    Переводит адаптер в режим monitor.

    Возвращает True при успехе, False при ошибке.
    Предполагает, что адаптер уже выбран пользователем.
    """
    if not interface_exists(interface):
        print(f"[-] Интерфейс {interface} не найден.")
        return False

    current = get_interface_mode(interface)
    if current.lower() == "monitor":
        print(f"[+] {interface} уже в режиме monitor.")
        return True

    phy = get_interface_phy(interface)
    print(f"[*] {interface} ({phy or 'phy?'}): переключаю {current} -> monitor")

    try:
        subprocess.run(["ip", "link", "set", interface, "down"], check=True)
        subprocess.run(["iw", "dev", interface, "set", "type", "monitor"], check=True)
        subprocess.run(["ip", "link", "set", interface, "up"], check=True)
        time.sleep(1)

        new_mode = get_interface_mode(interface)
        if new_mode.lower() == "monitor":
            print(f"[+] {interface} переведён в monitor.")
            return True

        print(f"[-] Режим после переключения: {new_mode}. Ожидался monitor.")
        print("[*] Драйвер адаптера может не поддерживать monitor mode.")
        return False

    except subprocess.CalledProcessError as e:
        print(f"[-] Ошибка переключения: {e}")
        return False


def set_managed_mode(interface):
    """
    Возвращает адаптер в режим managed.
    Полезно вызывать в finally при выходе из программы.
    """
    if not interface_exists(interface):
        return False

    current = get_interface_mode(interface)
    if current.lower() == "managed":
        return True

    try:
        subprocess.run(["ip", "link", "set", interface, "down"], check=True)
        subprocess.run(["iw", "dev", interface, "set", "type", "managed"], check=True)
        subprocess.run(["ip", "link", "set", interface, "up"], check=True)
        time.sleep(1)
        print(f"[+] {interface} возвращён в managed.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[-] Не удалось вернуть managed: {e}")
        return False