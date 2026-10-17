"""Сканирование Wi-Fi сетей через airodump-ng и разбор его CSV."""

import os
import re
import time
import signal
import subprocess
from pathlib import Path

from .terminal import find_terminal
from .constants import GREEN, RESET, AIRODUMP_BANDS


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


def choose_network(networks):
    """Показывает сети и просит выбрать номер. Возвращает сеть или None (отмена)."""
    display_networks(networks)
    while True:
        try:
            choice = input(
                f"\nВыберите номер сети (1-{len(networks)}, 0 — отмена): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[*] Отменено.")
            return None
        if choice == "":
            print("Пустой ввод. Введите число или 0 для отмены.")
            continue
        if choice == "0":
            print("[*] Отменено.")
            return None
        try:
            idx = int(choice) - 1
        except ValueError:
            print(f"Ошибка: нужно целое число от 0 до {len(networks)}.")
            continue
        if 0 <= idx < len(networks):
            return networks[idx]
        print(f"Ошибка: число должно быть от 1 до {len(networks)}.")


def scan_networks(interface, duration, work_dir):
    """
    Запускает airodump-ng в отдельном окне терминала и следит за CSV.
    Ctrl+C или истечение duration — останавливает сканирование. Возвращает список сетей.
    """
    work_dir = Path(work_dir)
    prefix = str(work_dir / "scan")
    csv_file = f"{prefix}-01.csv"

    airodump_cmd = (
        f'airodump-ng --band {AIRODUMP_BANDS} '
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
            launch = term_cmd + [f"bash {script_path}"]

        try:
            term_proc = subprocess.Popen(launch, preexec_fn=os.setsid)
        except Exception as e:
            print(f"[!] Не удалось открыть {term_name}: {e}")
            term_proc = None

    if term_proc is None:
        print("[!] Терминал не найден, запускаю сканирование здесь же.")
        cmd = ["airodump-ng", "--band", AIRODUMP_BANDS,
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
