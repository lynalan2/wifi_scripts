"""Управление Wi-Fi адаптером: список, режимы (monitor/managed), phy, канал, MAC.

Объединяет то, что раньше было размазано по adapters.py, adapter_ch_mode.py
и handshake.py.
"""

import re
import sys
import time
import subprocess

from .system import run


# ============ Информация об интерфейсе ============

def list_wifi_interfaces():
    """Список Wi-Fi интерфейсов через `iw dev`."""
    r = run(["iw", "dev"])
    if r.returncode != 0:
        return []
    return re.findall(r"Interface\s+(\S+)", r.stdout)


def get_interface_mode(interface):
    """Текущий тип интерфейса (managed, monitor, ...) или 'unknown'."""
    r = run(["iw", "dev", interface, "info"])
    m = re.search(r"type\s+(\w+)", r.stdout)
    return m.group(1) if m else "unknown"


def get_interface_phy(interface):
    """Имя phy (например 'phy0') для интерфейса, или None."""
    r = run(["iw", "dev", interface, "info"])
    m = re.search(r"wiphy\s+(\d+)", r.stdout)
    return f"phy{m.group(1)}" if m else None


def interface_exists(interface):
    return run(["iw", "dev", interface, "info"]).returncode == 0


def get_mac(interface):
    try:
        r = run(["ip", "link", "show", interface])
        m = re.search(r"link/ether\s+([0-9a-f:]{17})", r.stdout)
        return m.group(1) if m else "N/A"
    except Exception:
        return "N/A"


def get_wifi_info(interface):
    """Возвращает (режим, строку_скоростей)."""
    try:
        dev = subprocess.run(
            ["iw", "dev", interface, "info"],
            capture_output=True, text=True, check=True
        ).stdout

        mode_match = re.search(r"type\s+(\w+)", dev)
        mode = mode_match.group(1) if mode_match else "Неизвестно"

        phy_match = re.search(r"wiphy\s+(\d+)", dev)
        phy = phy_match.group(1) if phy_match else None

        speeds = []
        if phy is not None:
            phy_out = run(["iw", "phy", f"phy{phy}", "info"]).stdout
            for m in re.finditer(r"([\d.]+)\s*Mbps", phy_out):
                speeds.append(float(m.group(1)))

        if speeds:
            speeds = sorted(set(speeds))
            speed_str = f"{speeds[0]:g}-{speeds[-1]:g} Mbps"
        else:
            speed_str = "Неизвестно"
        return mode, speed_str
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Неизвестно", "Неизвестно"


# ============ Смена режима ============

def set_interface_mode(interface, mode):
    """Низкоуровневое переключение типа интерфейса (бросает CalledProcessError)."""
    subprocess.run(["ip", "link", "set", interface, "down"], check=True)
    subprocess.run(["iw", "dev", interface, "set", "type", mode], check=True)
    subprocess.run(["ip", "link", "set", interface, "up"], check=True)


def set_channel(interface, channel):
    """Фиксирует канал адаптера (тихо, без исключений)."""
    subprocess.run(["iw", "dev", interface, "set", "channel", str(channel)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reset_monitor(interface):
    """
    Сбрасывает залипший канал/бэнд (например, после атаки на 5 ГГц адаптер
    мог застрять и не хопать на 2.4 ГГц). Цикл monitor через managed. Тихо.
    """
    q = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        subprocess.run(["ip", "link", "set", interface, "down"], **q)
        subprocess.run(["iw", "dev", interface, "set", "type", "managed"], **q)
        subprocess.run(["iw", "dev", interface, "set", "type", "monitor"], **q)
        subprocess.run(["ip", "link", "set", interface, "up"], **q)
    except Exception:
        pass


def add_monitor_vif(base_iface, name=None):
    """
    Создаёт виртуальный monitor-интерфейс на том же радио, что base_iface.
    Нужно для деаутентификации одним адаптером, пока на нём работает AP
    (как делает airgeddon). Возвращает имя VIF или None, если драйвер не умеет.
    """
    name = name or f"{base_iface}mon"
    r = subprocess.run(
        ["iw", "dev", base_iface, "interface", "add", name, "type", "monitor"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return None
    subprocess.run(["ip", "link", "set", name, "up"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return name


def del_interface(name):
    """Удаляет интерфейс (например, созданный add_monitor_vif). Тихо."""
    subprocess.run(["iw", "dev", name, "del"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def set_monitor_mode(interface):
    """Переводит адаптер в monitor. True при успехе, False при ошибке."""
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
        set_interface_mode(interface, "monitor")
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
    """Возвращает адаптер в managed. True при успехе, False при ошибке."""
    if not interface_exists(interface):
        return False
    if get_interface_mode(interface).lower() == "managed":
        return True
    try:
        set_interface_mode(interface, "managed")
        time.sleep(1)
        print(f"[+] {interface} возвращён в managed.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[-] Не удалось вернуть managed: {e}")
        return False


def ensure_monitor(interface):
    """Гарантирует monitor (тихий вариант для автозапуска). True/False."""
    if get_interface_mode(interface).lower() == "monitor":
        print(f"[+] {interface} уже в режиме monitor.")
        return True
    print(f"[*] Перевод {interface} в monitor")
    try:
        set_interface_mode(interface, "monitor")
        print("[+] Готово.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[-] Не удалось переключить режим: {e}")
        return False


def restore_managed(interface):
    """Если адаптер в monitor — вернуть в managed (без исключений)."""
    try:
        if get_interface_mode(interface).lower() == "monitor":
            print(f"[*] Возвращаю {interface} в managed...")
            set_interface_mode(interface, "managed")
    except Exception:
        pass


# ============ Выбор адаптера ============

def get_name_mac_type_adapters():
    """Спрашивает пользователя, какой адаптер использовать. (имя, {mode, speed})."""
    ifaces = list_wifi_interfaces()
    if not ifaces:
        print("[-] Не найдено ни одного Wi-Fi интерфейса (iw dev пуст).")
        print("    Проверь: lsusb, rfkill list, dmesg | tail")
        sys.exit(1)

    for iface in ifaces:
        subprocess.run(["ip", "link", "set", iface, "up"], capture_output=True)

    print("\nДоступные Wi-Fi адаптеры:")
    for i, iface in enumerate(ifaces, start=1):
        mode, speed = get_wifi_info(iface)
        print(f"  {i}. {iface}  ({mode}, {speed})")

    while True:
        try:
            user_input = input("\nВведите номер адаптера (0 — выход): ").strip()
            if user_input == '0':
                sys.exit(0)
            idx = int(user_input) - 1
            if 0 <= idx < len(ifaces):
                chosen = ifaces[idx]
                break
            print(f"Ошибка: введите число от 1 до {len(ifaces)}.")
        except ValueError:
            print("Ошибка: нужно ввести целое число.")

    mode, speed = get_wifi_info(chosen)
    return chosen, {"mode": mode, "speed": speed}
