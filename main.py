

import os
import sys
import time
import subprocess
import re
from cracker import cracker_menu

from adapters import get_name_mac_type_adapters, get_wifi_info
from adapter_ch_mode import (
    set_monitor_mode,
    set_managed_mode,
    get_interface_mode,
    get_interface_phy,
    interface_exists,
)
from handshake import handshake_flow


# ============ Интерфейс ============

def clear_screen():
    os.system('clear')


def get_mac(interface):
    try:
        r = subprocess.run(
            ["ip", "link", "show", interface],
            capture_output=True, text=True
        )
        m = re.search(r"link/ether\s+([0-9a-f:]{17})", r.stdout)
        return m.group(1) if m else "N/A"
    except Exception:
        return "N/A"


def print_header(interface):
    """Шапка: состояние адаптера. Печатается после clear_screen."""
    mode = get_interface_mode(interface)
    phy = get_interface_phy(interface) or "?"
    mac = get_mac(interface)
    speed = get_wifi_info(interface)[1]

    print("=" * 62)
    print("  WiFi Tool")
    print("=" * 62)
    print(f"  Адаптер:  {interface}")
    print(f"  PHY:      {phy}")
    print(f"  Режим:    {mode}")
    print(f"  Скорость: {speed}")
    print(f"  MAC:      {mac}")
    print("=" * 62)


def pause():
    input("\nEnter — продолжить...")


# ============ Меню ============

def main_menu(interface):
    """
    Возвращает:
      'change' — сменить адаптер
      'exit'   — выйти из программы
    """
    while True:
        clear_screen()
        print_header(interface)
        print()
        print("  1. Включить режим monitor")
        print("  2. Включить режим managed")
        print("  3. Анализ сети")
        print("  4. Взлом пароля")
        print()
        print("  0. Сменить адаптер")
        print("  9. Выход")
        print()

        choice = input("Выбор: ").strip()

        if choice == '1':
            set_monitor_mode(interface)
            pause()

        elif choice == '2':
            set_managed_mode(interface)
            pause()

        elif choice == '3':
            if get_interface_mode(interface).lower() != "monitor":
                print("\n[-] Сначала включите режим monitor (пункт 1).")
                pause()
                continue
            try:
                handshake_flow(interface)
            except KeyboardInterrupt:
                print("\n[*] Прервано.")
            pause()

        elif choice == '4':
            try:
                cracker_menu()
            except KeyboardInterrupt:
                print("\n[*] Прервано.")
            pause()

        elif choice == '0':
            return 'change'

        elif choice == '9':
            return 'exit'

        else:
            print("Неизвестный пункт.")
            time.sleep(1)




def check_root():
    if os.geteuid() != 0:
        print("[-] Запустите с sudo.")
        sys.exit(1)

def ask_restore_managed(interface):
    """
    Спрашивает, возвращать ли адаптер в managed при выходе.
    Возвращает True/False.
    """
    print()
    print(f"[?] Вернуть {interface} в режим managed перед выходом?")
    print("    Y — вернуть (адаптер снова сможет подключаться к Wi-Fi)")
    print("    N — оставить как есть (monitor)")
    while True:
        ans = input("Выбор (Y/n): ").strip().lower()
        if ans in ('', 'y', 'yes', 'д', 'да'):
            return True
        if ans in ('n', 'no', 'н', 'нет'):
            return False
        print("Введите Y или N.")

def main():
    check_root()

    while True:
        clear_screen()
        print("=" * 62)
        print("  WiFi Tool")
        print("=" * 62)

        try:
            interface, _info = get_name_mac_type_adapters()
        except SystemExit:
            return
        except KeyboardInterrupt:
            print("\nВыход.")
            return

        if not interface_exists(interface):
            print(f"[-] Интерфейс {interface} пропал. Выберите снова.")
            pause()
            continue

        result = main_menu(interface)

        if result == 'exit':
            if get_interface_mode(interface).lower() == "monitor":
                if ask_restore_managed(interface):
                    print("\n[*] Возвращаю адаптер в managed...")
                    set_managed_mode(interface)
                else:
                    print("[*] Адаптер оставлен в monitor.")
            return
        


if __name__ == '__main__':
    main()