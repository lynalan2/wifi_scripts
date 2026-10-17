"""Главный цикл программы: выбор адаптера и построение меню из реестра FEATURES."""

import time

from . import iface
from .system import check_root
from .ui import clear_screen, pause, ask_yes_no, print_title
from .menu import FEATURES


def print_header(interface):
    """Шапка со статусом адаптера."""
    mode = iface.get_interface_mode(interface)
    phy = iface.get_interface_phy(interface) or "?"
    mac = iface.get_mac(interface)
    speed = iface.get_wifi_info(interface)[1]

    print_title("WiFi Tool")
    print(f"  Адаптер:  {interface}")
    print(f"  PHY:      {phy}")
    print(f"  Режим:    {mode}")
    print(f"  Скорость: {speed}")
    print(f"  MAC:      {mac}")
    print("=" * 62)


def _print_menu(interface):
    print_header(interface)
    print()
    print("  Адаптер:")
    print("    1. Включить режим monitor")
    print("    2. Включить режим managed")

    # Секции-фичи из реестра (группируем по group в порядке появления).
    last_group = None
    for feat in FEATURES:
        if feat.group != last_group:
            print()
            print(f"  {feat.group}:")
            last_group = feat.group
        print(f"    {feat.key}. {feat.label}")

    print()
    print("    0. Сменить адаптер")
    print("    9. Выход")
    print()


def main_menu(interface):
    """Возвращает 'change' или 'exit'."""
    features = {f.key: f for f in FEATURES}
    while True:
        clear_screen()
        _print_menu(interface)
        choice = input("Выбор: ").strip()

        if choice == '1':
            iface.set_monitor_mode(interface)
            pause()
        elif choice == '2':
            iface.set_managed_mode(interface)
            pause()
        elif choice == '0':
            return 'change'
        elif choice == '9':
            return 'exit'
        elif choice in features:
            feat = features[choice]
            if feat.needs_monitor and iface.get_interface_mode(interface).lower() != "monitor":
                print("\n[-] Сначала включите режим monitor (пункт 1).")
                pause()
                continue
            try:
                feat.run(interface)
            except KeyboardInterrupt:
                print("\n[*] Прервано.")
            pause()
        else:
            print("Неизвестный пункт.")
            time.sleep(1)


def main():
    check_root()
    while True:
        clear_screen()
        print_title("WiFi Tool")
        try:
            interface, _info = iface.get_name_mac_type_adapters()
        except SystemExit:
            return
        except KeyboardInterrupt:
            print("\nВыход.")
            return

        if not iface.interface_exists(interface):
            print(f"[-] Интерфейс {interface} пропал. Выберите снова.")
            pause()
            continue

        if main_menu(interface) == 'exit':
            if iface.get_interface_mode(interface).lower() == "monitor":
                if ask_yes_no(f"\n[?] Вернуть {interface} в режим managed перед выходом?"):
                    print("\n[*] Возвращаю адаптер в managed...")
                    iface.set_managed_mode(interface)
                else:
                    print("[*] Адаптер оставлен в monitor.")
            return
