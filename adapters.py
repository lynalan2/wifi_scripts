#!/usr/bin/env python3
import sys
import subprocess
import re


def list_wifi_interfaces():
    """Возвращает список Wi-Fi интерфейсов через iw dev."""
    r = subprocess.run(["iw", "dev"], capture_output=True, text=True)
    if r.returncode != 0:
        return []
    
    return re.findall(r"Interface\s+(\S+)", r.stdout)


def get_wifi_info(interface: str):
    try:
        dev_result = subprocess.run(
            ["iw", "dev", interface, "info"],
            capture_output=True, text=True, check=True
        )
        dev_out = dev_result.stdout

        mode_match = re.search(r"type\s+(\w+)", dev_out)
        mode = mode_match.group(1) if mode_match else "Неизвестно"

        phy_match = re.search(r"wiphy\s+(\d+)", dev_out)
        phy = phy_match.group(1) if phy_match else None

        speeds = []
        if phy is not None:
            phy_result = subprocess.run(
                ["iw", "phy", f"phy{phy}", "info"],
                capture_output=True, text=True
            )
            for m in re.finditer(r"([\d.]+)\s*Mbps", phy_result.stdout):
                speeds.append(float(m.group(1)))

        if speeds:
            speeds = sorted(set(speeds))
            speed_str = f"{speeds[0]:g}-{speeds[-1]:g} Mbps"
        else:
            speed_str = "Неизвестно"

        return mode, speed_str

    except subprocess.CalledProcessError:
        return "Неизвестно", "Неизвестно"
    except FileNotFoundError:
        return "Неизвестно", "Неизвестно"


def get_name_mac_type_adapters():
    ifaces = list_wifi_interfaces()
    if not ifaces:
        print("[-] Не найдено ни одного Wi-Fi интерфейса (iw dev пуст).")
        print("    Проверь: lsusb, rfkill list, dmesg | tail")
        sys.exit(1)

    # Поднимаем интерфейсы, чтобы точно были доступны
    for iface in ifaces:
        subprocess.run(["ip", "link", "set", iface, "up"],
                       capture_output=True)

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