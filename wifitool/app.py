"""Главный цикл программы: выбор языка, адаптера и построение меню из FEATURES."""

import time

from . import iface
from . import deps
from .system import check_root
from .ui import clear_screen, pause, ask_yes_no, print_title
from .menu import FEATURES
from .i18n import t, saved_lang, choose_language_interactive


def print_header(interface):
    """Шапка со статусом адаптера."""
    mode = iface.get_interface_mode(interface)
    phy = iface.get_interface_phy(interface) or "?"
    mac = iface.get_mac(interface)
    speed = iface.get_wifi_info(interface)[1]

    print_title(t("app.title"))
    print(t("app.adapter", v=interface))
    print(t("app.phy", v=phy))
    print(t("app.mode", v=mode))
    print(t("app.speed", v=speed))
    print(t("app.mac", v=mac))
    print("=" * 62)


def _print_menu(interface):
    print_header(interface)
    print()
    print(t("app.grp_adapter"))
    print(t("app.mon_on"))
    print(t("app.managed_on"))

    # Секции-фичи из реестра (группируем по group в порядке появления).
    last_group = None
    for feat in FEATURES:
        if feat.group_key != last_group:
            print()
            print(f"  {t(feat.group_key)}:")
            last_group = feat.group_key
        print(f"    {feat.key}. {t(feat.label_key)}")

    print()
    print(t("app.change_adapter"))
    print(t("app.deps"))
    print(t("app.language"))
    print(t("app.exit"))
    print()


def main_menu(interface):
    """Возвращает 'change' или 'exit'."""
    features = {f.key: f for f in FEATURES}
    while True:
        clear_screen()
        _print_menu(interface)
        choice = input(t("common.choice")).strip()

        if choice == '1':
            iface.set_monitor_mode(interface)
            pause()
        elif choice == '2':
            iface.set_managed_mode(interface)
            pause()
        elif choice == '7':
            deps.deps_menu()
        elif choice == '8':
            choose_language_interactive()
        elif choice == '0':
            return 'change'
        elif choice == '9':
            return 'exit'
        elif choice in features:
            feat = features[choice]
            if feat.needs_monitor and iface.get_interface_mode(interface).lower() != "monitor":
                print(t("app.need_monitor"))
                pause()
                continue
            try:
                feat.run(interface)
            except KeyboardInterrupt:
                print(t("common.interrupted"))
            pause()
        else:
            print(t("common.unknown_item"))
            time.sleep(0.5)


def main():
    check_root()
    # Первый запуск — спросить язык; дальше берём сохранённый.
    if saved_lang() is None:
        choose_language_interactive(first_time=True)

    # Необязательная стартовая подсказка (как таблица тулзов в airgeddon):
    # не блокируем, но сообщаем, если нет важных утилит.
    missing_essential = deps.essential_missing()
    if missing_essential:
        print(t("app.deps_hint", tools=", ".join(missing_essential)))
        pause()

    while True:
        clear_screen()
        print_title(t("app.title"))
        try:
            interface, _info = iface.get_name_mac_type_adapters()
        except SystemExit:
            return
        except KeyboardInterrupt:
            print(t("app.exit_word"))
            return

        if not iface.interface_exists(interface):
            print(t("app.iface_gone", iface=interface))
            pause()
            continue

        if main_menu(interface) == 'exit':
            if iface.get_interface_mode(interface).lower() == "monitor":
                if ask_yes_no(t("app.ask_restore", iface=interface)):
                    print(t("app.restoring"))
                    iface.set_managed_mode(interface)
                else:
                    print(t("app.left_monitor"))
            return
