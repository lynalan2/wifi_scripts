"""Проверка внешних утилит и (опциональная) установка недостающих.

Как в airgeddon: показываем таблицу «установлено / нет». Дополнительно, если
доступен поддерживаемый пакетный менеджер, предлагаем доустановить недостающее
(с подтверждением). Сторонних Python-библиотек у проекта нет — только эти CLI.
"""

import shutil
import subprocess

from .ui import pause, ask_yes_no, print_title
from .i18n import t

# (бинарник, пакет в apt, категория, essential)
TOOLS = [
    ("iw",            "iw",          "core",     True),
    ("ip",            "iproute2",    "core",     True),
    ("airodump-ng",   "aircrack-ng", "capture",  True),
    ("aireplay-ng",   "aircrack-ng", "capture",  True),
    ("aircrack-ng",   "aircrack-ng", "capture",  True),
    ("hcxdumptool",   "hcxdumptool", "capture",  True),
    ("hcxpcapngtool", "hcxtools",    "capture",  True),
    ("hashcat",       "hashcat",     "crack",    True),
    ("wget",          "wget",        "crack",    True),
    ("hostapd",       "hostapd",     "eviltwin", True),
    ("dnsmasq",       "dnsmasq",     "eviltwin", True),
    ("iptables",      "iptables",    "eviltwin", True),
    ("xterm",         "xterm",       "ui",       True),
    ("rfkill",        "rfkill",      "optional", False),
    ("bettercap",     "bettercap",   "optional", False),
    ("beef-xss",      "beef-xss",    "optional", False),
    ("mdk4",          "mdk4",        "optional", False),
]

CATEGORY_ORDER = ["core", "capture", "crack", "eviltwin", "ui", "optional"]


def _pkg_manager():
    """Возвращает (имя, базовая команда установки) или (None, None).
    Автоустановку делаем только для apt — имена пакетов здесь под Debian/Kali."""
    if shutil.which("apt-get"):
        return "apt", ["apt-get", "install", "-y"]
    for mgr in ("pacman", "dnf", "zypper"):
        if shutil.which(mgr):
            return mgr, None   # есть менеджер, но автоустановку не делаем (имена иные)
    return None, None


def _status():
    """Список (binary, pkg, category, essential, installed)."""
    return [(b, p, c, e, shutil.which(b) is not None) for b, p, c, e in TOOLS]


def report():
    """Печатает таблицу зависимостей. Возвращает список недостающих бинарников."""
    rows = _status()
    print()
    print("  {:<16} {:<13} {}".format(
        t("deps.col_tool"), t("deps.col_status"), t("deps.col_pkg")))
    print("  " + "-" * 46)
    missing = []
    for cat in CATEGORY_ORDER:
        cat_rows = [r for r in rows if r[2] == cat]
        if not cat_rows:
            continue
        print(f"  [{t('deps.cat_' + cat)}]")
        for binary, pkg, _cat, essential, installed in cat_rows:
            mark = t("deps.installed") if installed else t("deps.missing")
            tagless = "" if essential else " *"
            print("  {:<16} {:<13} {}".format(binary + tagless, mark, pkg))
            if not installed:
                missing.append((binary, pkg, essential))
    print()
    print(t("deps.optional_note"))
    return missing


def _missing_packages(missing, essential_only=False):
    pkgs = []
    for _binary, pkg, essential in missing:
        if essential_only and not essential:
            continue
        if pkg not in pkgs:
            pkgs.append(pkg)
    return pkgs


def deps_menu():
    print_title(t("deps.title"))
    missing = report()

    if not missing:
        print(t("deps.all_ok"))
        pause()
        return

    ess = sum(1 for _b, _p, e in missing if e)
    print(t("deps.summary", n=len(missing), e=ess))

    mgr, install_cmd = _pkg_manager()
    pkgs = _missing_packages(missing)

    if install_cmd is None:
        # менеджера apt нет — показываем, что поставить вручную
        if mgr:
            print(t("deps.manual_only", mgr=mgr, pkgs=" ".join(pkgs)))
        else:
            print(t("deps.no_pkgmgr"))
            print(t("deps.suggest", cmd="<package-manager> install " + " ".join(pkgs)))
        pause()
        return

    if not ask_yes_no(t("deps.ask_install", mgr=mgr), default=True):
        pause()
        return

    print(t("deps.installing", pkgs=" ".join(pkgs)))
    try:
        rc = subprocess.run(install_cmd + pkgs).returncode
    except Exception as e:
        print(t("deps.install_fail", code=e))
        pause()
        return
    if rc == 0:
        print(t("deps.install_done"))
    else:
        print(t("deps.install_fail", code=rc))
    pause()


def essential_missing():
    """Список недостающих ESSENTIAL бинарников (для стартовой подсказки)."""
    return [b for b, _p, _c, e, installed in _status() if e and not installed]
