#!/usr/bin/env python3
"""
Взлом WPA/WPA2 handshake через hashcat.
Управление cap-файлами, словарями, сессиями и результатами.
"""

import os
import json
import shutil
import subprocess
import time
import re
from pathlib import Path

from wifitool.constants import (
    BASE_DIR, DATA_DIR, STATE_FILE, WORDLISTS_DIR,
    CAPTURES_DIR, SESSIONS_DIR, ROCKYOU_URL,
)
from wifitool.terminal import find_terminal, launch_in_terminal, kill_group, sh_quote
from wifitool.i18n import t
from wifitool.hashfile import (
    read_hashes as _read_hashes,
    decode_hashcat_plain as _decode_hashcat_plain,
    essid_from_hash as _essid_from_hash,
    parse_out_line as _parse_out_line,
)

HASHCAT_POTFILE = Path.home() / ".local/share/hashcat/hashcat.potfile"


# ============ Состояние ============

def init_dirs():
    DATA_DIR.mkdir(exist_ok=True)
    WORDLISTS_DIR.mkdir(exist_ok=True)
    CAPTURES_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)


def load_state():
    init_dirs()
    if not STATE_FILE.exists():
        return {
            "caps": [],        # [{"path": "...", "name": "...", "hc22000": "...", "session": null, "progress": 0, "cracked": false}]
            "wordlists": [],   # [{"path": "...", "name": "..."}]
            "cracked": [],     # [{"essid": "...", "password": "...", "cap": "..."}]
        }
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"caps": [], "wordlists": [], "cracked": []}


def save_state(state):
    # Пишем во временный файл и атомарно заменяем, чтобы прерывание посреди
    # записи (Ctrl+C) не оставило битый state.json.
    init_dirs()
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)


# ============ Управление cap ============

def add_cap(state):
    print(t("crack.ask_cap"))
    path = input(t("crack.path")).strip()
    if not path:
        return
    p = Path(path).expanduser()
    if not p.exists():
        print(t("crack.file_not_found", p=p))
        return
    if p.suffix.lower() != ".cap":
        print(t("crack.expect_cap"))
        return

    name = input(t("crack.ask_name")).strip() or p.stem

    # Конвертируем в .hc22000
    hc22000 = CAPTURES_DIR / f"{p.stem}.hc22000"
    print(t("crack.converting", a=p.name, b=hc22000.name))
    r = subprocess.run(
        ["hcxpcapngtool", "-o", str(hc22000), str(p)],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not hc22000.exists():
        print(t("crack.conv_err"))
        print(r.stderr or r.stdout)
        return

    state["caps"].append({
        "path": str(p.resolve()),
        "name": name,
        "hc22000": str(hc22000),
        "session": None,
        "progress": 0,
        "cracked": False,
    })
    save_state(state)
    print(t("crack.added", name=name))


def _unique_hc_path(name):
    dest = CAPTURES_DIR / f"{name}.hc22000"
    n = 1
    while dest.exists():
        dest = CAPTURES_DIR / f"{name}_{n}.hc22000"
        n += 1
    return dest


def add_hc22000(state):
    path = input(t("crack.ask_hc")).strip()
    if not path:
        return
    p = Path(path).expanduser()
    if not p.exists():
        print(t("crack.file_not_found", p=p))
        return
    if p.suffix.lower() != ".hc22000":
        print(t("crack.expect_hc"))
        return

    lines = _read_hashes(p)
    if not any(l.startswith("WPA*") for l in lines):
        print(t("crack.not_hc"))
        return

    name = input(t("crack.ask_name")).strip() or p.stem
    init_dirs()
    dest = _unique_hc_path(name)
    try:
        shutil.copy2(p, dest)
    except Exception as e:
        print(t("crack.copy_fail", e=e))
        return

    state["caps"].append({
        "path": str(p.resolve()),
        "name": name,
        "hc22000": str(dest),
        "session": None,
        "progress": 0,
        "cracked": False,
    })
    save_state(state)
    print(t("crack.added_as", name=name, dest=dest.name))


def remove_cap(state):
    if not state["caps"]:
        print(t("crack.cap_empty"))
        return
    for i, c in enumerate(state["caps"], 1):
        print(f"  {i}. {c['name']}  [{c['path']}]")
    try:
        idx = int(input(t("crack.del_prompt")).strip()) - 1
    except ValueError:
        return
    if 0 <= idx < len(state["caps"]):
        c = state["caps"].pop(idx)
        # удаляем сконвертированный hc22000
        try:
            Path(c["hc22000"]).unlink(missing_ok=True)
        except Exception:
            pass
        save_state(state)
        print(t("crack.deleted", name=c["name"]))


def list_caps(state):
    if not state["caps"]:
        print(t("crack.cap_empty"))
        return
    print("\n{:<4} {:<20} {:<10} {:<8} {}".format(
        "№", t("crack.col_name"), t("crack.col_progress"),
        t("crack.col_cracked"), t("crack.col_path")
    ))
    print("-" * 90)
    for i, c in enumerate(state["caps"], 1):
        print("{:<4} {:<20} {:<10} {:<8} {}".format(
            i, c["name"][:18], f"{c.get('progress', 0)}%",
            t("crack.yes") if c.get("cracked") else t("crack.no"), c["path"]
        ))


# ============ Управление словарями ============

def add_wordlist(state):
    print(t("crack.ask_wl"))
    path = input(t("crack.path")).strip()
    if not path:
        return
    p = Path(path).expanduser()
    if not p.exists():
        print(t("crack.file_not_found", p=p))
        return
    name = input(t("crack.ask_name")).strip() or p.stem
    state["wordlists"].append({"path": str(p.resolve()), "name": name})
    save_state(state)
    print(t("crack.wl_added", name=name))


def remove_wordlist(state):
    if not state["wordlists"]:
        print(t("crack.wl_empty"))
        return
    for i, w in enumerate(state["wordlists"], 1):
        print(f"  {i}. {w['name']}  [{w['path']}]")
    try:
        idx = int(input(t("crack.del_prompt")).strip()) - 1
    except ValueError:
        return
    if 0 <= idx < len(state["wordlists"]):
        w = state["wordlists"].pop(idx)
        save_state(state)
        print(t("crack.wl_deleted", name=w["name"]))


def list_wordlists(state):
    if not state["wordlists"]:
        print(t("crack.wl_empty"))
        print(t("crack.wl_hint", dir=WORDLISTS_DIR))
        return
    print("\n{:<4} {:<20} {}".format("№", t("crack.col_name"), t("crack.col_path")))
    print("-" * 70)
    for i, w in enumerate(state["wordlists"], 1):
        print("{:<4} {:<20} {}".format(i, w["name"][:18], w["path"]))


def ensure_default_wordlist(state):
    """Если словарей нет — предлагает скачать rockyou."""
    if state["wordlists"]:
        return
    print(t("crack.no_wl_title"))
    ans = input(t("crack.ask_rockyou")).strip().lower()
    if ans == 'n':
        return
    dest = WORDLISTS_DIR / "rockyou.txt"
    if not dest.exists():
        print(t("crack.downloading"))
        r = subprocess.run(
            ["wget", "-q", "-O", str(dest), ROCKYOU_URL],
            capture_output=True, text=True
        )
        if r.returncode != 0 or not dest.exists():
            print(t("crack.dl_fail"))
            return
    state["wordlists"].append({"path": str(dest), "name": "rockyou"})
    save_state(state)
    print(t("crack.rockyou_added", dest=dest))


# ============ Сессии и прогресс ============

def _parse_progress(log_file):
    """Читает последнюю строку Progress из нашего log-файла hashcat."""
    if not os.path.exists(log_file):
        return 0
    try:
        with open(log_file, "r", errors="ignore") as f:
            text = f.read()
    except Exception:
        return 0

    # hashcat печатает статус через \r — нормализуем
    text = text.replace("\r", "\n")
    matches = re.findall(r"Progress\.+:\s*\d+/\d+\s+\(([\d.]+)%\)", text)
    if matches:
        return int(float(matches[-1]))
    return 0

def list_sessions(state):
    sessions = [c for c in state["caps"] if c.get("session") and not c.get("cracked")]
    if not sessions:
        print(t("crack.no_sessions"))
        return
    print("\n{:<4} {:<20} {:<10} {}".format(
        "№", t("crack.col_name"), t("crack.col_progress"), t("crack.col_session")))
    print("-" * 70)
    for i, c in enumerate(sessions, 1):
        print("{:<4} {:<20} {:<10} {}".format(
            i, c["name"][:18], f"{c.get('progress', 0)}%", c["session"]
        ))


# ============ Взлом ============

def run_cracking(state):
    if not state["caps"]:
        print(t("crack.no_caps"))
        return
    if not state["wordlists"]:
        print(t("crack.no_wls"))
        return

    # выбор cap
    print(t("crack.pick_cap"))
    for i, c in enumerate(state["caps"], 1):
        if c.get("cracked"):
            status = t("crack.st_cracked")
        elif c.get("progress", 0) >= 100:
            status = t("crack.st_exhausted")
        else:
            status = f"{c.get('progress', 0)}%"
        print(f"  {i}. {c['name']}  [{status}]")
    try:
        idx = int(input(t("crack.num_prompt")).strip()) - 1
    except ValueError:
        return
    if not (0 <= idx < len(state["caps"])):
        return
    cap = state["caps"][idx]

    if cap.get("cracked"):
        print(t("crack.already"))
        return

    # выбор словаря
    print(t("crack.pick_wl"))
    for i, w in enumerate(state["wordlists"], 1):
        print(f"  {i}. {w['name']}")
    try:
        widx = int(input(t("crack.num_prompt")).strip()) - 1
    except ValueError:
        return
    if not (0 <= widx < len(state["wordlists"])):
        return
    wordlist = state["wordlists"][widx]

    # Если словарь другой или прошлая сессия завершена (100%) — начинаем заново
    new_wordlist = cap.get("session_wordlist") != wordlist["path"]
    finished = cap.get("progress", 0) >= 100

    if new_wordlist or finished:
        # старые файлы сессии (если есть) больше не нужны
        old_sess = cap.get("session")
        if old_sess:
            for p in (DATA_DIR / f"crack_{old_sess}.sh",
                      DATA_DIR / f"log_{old_sess}.txt",
                      DATA_DIR / f"out_{old_sess}.txt",
                      SESSIONS_DIR / f"{old_sess}.restore"):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

        cap["session"] = None
        cap["progress"] = 0
        cap["cracked"] = False

    session_name = cap["session"] or f"cap_{int(time.time())}"
    cap["session"] = session_name
    cap["session_wordlist"] = wordlist["path"]     # ← запоминаем словарь сессии

    out_file = DATA_DIR / f"out_{session_name}.txt"
    log_file = DATA_DIR / f"log_{session_name}.txt"
    # Явный путь к restore-файлу — не угадываем папку сессий hashcat, а держим
    # её у себя: так возобновление и очистка всегда работают с одним местом.
    restore_file = SESSIONS_DIR / f"{session_name}.restore"

    # --- команда hashcat ---
    # potfile выключаем через --potfile-disable, чтобы не пересекаться с чужими сессиями
    common = (
        f'hashcat -m 22000 -a 0 '
        f'--session {session_name} '
        f'--restore-file-path "{restore_file}" '
        f'--status --status-timer 2 '
        f'--potfile-disable '
        f'-o "{out_file}" '
    )

    # Возобновляемся только если прогресс есть И restore-файл реально на месте.
    if cap.get("progress", 0) > 0 and restore_file.exists():
        hashcat_cmd = f'{common}--restore'
        print(t("crack.resume", s=session_name, p=cap["progress"]))
    else:
        if cap.get("progress", 0) > 0:
            print(t("crack.no_restore"))
            cap["progress"] = 0
        hashcat_cmd = f'{common}"{cap["hc22000"]}" "{wordlist["path"]}"'
        print(t("crack.new_session", s=session_name))

    # --- bash-обёртка ---
    script_path = DATA_DIR / f"crack_{session_name}.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        f"echo {sh_quote(t('crack.win_title', name=cap['name']))}\n"
        f"echo {sh_quote(t('crack.win_session', s=session_name))}\n"
        f"echo {sh_quote(t('crack.win_wl', w=wordlist['name']))}\n"
        f"echo {sh_quote(t('crack.win_stop'))}\n"
        "echo\n"
        f"cd {DATA_DIR}\n"
        # tee: вывод в окно + в файл. -u чтобы не буферизировало
        f"stdbuf -oL -eL {hashcat_cmd} 2>&1 | tee \"{log_file}\"\n"
    )
    script_path.chmod(0o755)

    term_name, term_cmd = find_terminal()
    if term_name is None:
        print(t("crack.no_term"))
        return

    proc = launch_in_terminal(term_name, term_cmd, script_path)
    if proc is None:
        return

    print(t("crack.started", term=term_name))
    print(t("crack.watching"))

    try:
        while proc.poll() is None:
            time.sleep(2)
            new_p = _parse_progress(log_file)
            if new_p > cap.get("progress", 0):
                cap["progress"] = new_p
            if _check_cracked(state, cap, out_file):
                print(t("crack.pw_found", name=cap["name"]))
                save_state(state)
                kill_group(proc)
                break
            print(t("crack.progress", p=cap["progress"]), end="", flush=True)
    except KeyboardInterrupt:
        print(t("crack.stopping"))
    finally:
        # финальное обновление перед выходом — вдруг hashcat успел записать
        new_p = _parse_progress(log_file)
        if new_p > cap.get("progress", 0):
            cap["progress"] = new_p
        _check_cracked(state, cap, out_file)
        if cap.get("cracked"):
            cap["progress"] = 100
        save_state(state)
        kill_group(proc)
        time.sleep(1)

    if cap.get("cracked"):
        print(t("crack.done", name=cap["name"]))
    else:
        print(t("crack.session_saved", s=session_name, p=cap.get("progress", 0)))


def list_cracked(state):
    if not state["cracked"]:
        print(t("crack.none_cracked"))
        return
    print("\n{:<30} {:<30} {}".format(t("crack.col_net"), t("crack.col_pw"), "Cap"))
    print("-" * 80)
    for c in state["cracked"]:
        print("{:<30} {:<30} {}".format(
            str(c["essid"])[:28],
            str(c["password"])[:28],
            str(c["cap"])[:40],
        ))

def _check_cracked(state, cap, out_file):
    """
    Читает out-файл hashcat, вытаскивает ESSID и пароль, сверяет с .hc22000
    и регистрирует находку в state["cracked"].
    """
    if not os.path.exists(out_file):
        return False

    hashes = _read_hashes(cap["hc22000"])
    if not hashes:
        return False

    valid_essids = set()
    for h in hashes:
        e = _essid_from_hash(h)
        if e:
            valid_essids.add(e)

    try:
        with open(out_file, "r", errors="ignore") as f:
            lines = [l.strip() for l in f if l.strip()]
    except Exception:
        return False
    if not lines:
        return False

    found_any = False
    for line in lines:
        parsed = _parse_out_line(line, valid_essids)
        if parsed is None:
            continue
        essid, password = parsed
        if not password:
            continue

        # Фильтруем по ESSID только если он известен и из этого cap-файла.
        if essid and valid_essids and essid not in valid_essids:
            continue

        already = any(
            c.get("cap") == cap["name"] and c.get("password") == password
            for c in state["cracked"]
        )
        if not already:
            state["cracked"].append({
                "essid": essid,
                "password": password,
                "cap": cap["name"],
            })
            print(t("crack.pw_got", essid=essid, password=password))
        found_any = True

    if found_any:
        cap["cracked"] = True
        save_state(state)
    return found_any

# ============ Меню ============

def cracker_menu():
    state = load_state()
    ensure_default_wordlist(state)

    while True:
        os.system("clear")
        print("=" * 62)
        print(f"  {t('crack.menu_title')}")
        print("=" * 62)
        print()
        print(t("crack.grp_files"))
        print(t("crack.m_add_cap"))
        print(t("crack.m_add_hc"))
        print(t("crack.m_del_cap"))
        print(t("crack.m_list_cap"))
        print()
        print(t("crack.grp_wl"))
        print(t("crack.m_add_wl"))
        print(t("crack.m_del_wl"))
        print(t("crack.m_list_wl"))
        print()
        print(t("crack.grp_crack"))
        print(t("crack.m_run"))
        print(t("crack.m_sessions"))
        print(t("crack.m_cracked"))
        print()
        print(t("crack.m_back"))
        print()

        choice = input(t("common.choice")).strip()

        if choice == '1':
            add_cap(state)
        elif choice == '2':
            add_hc22000(state)
        elif choice == '3':
            remove_cap(state)
        elif choice == '4':
            list_caps(state)
        elif choice == '5':
            add_wordlist(state)
        elif choice == '6':
            remove_wordlist(state)
        elif choice == '7':
            list_wordlists(state)
        elif choice == '8':
            run_cracking(state)
        elif choice == '9':
            list_sessions(state)
        elif choice == '10':
            list_cracked(state)
        elif choice == '0':
            return
        else:
            print(t("common.unknown_item"))

        input(t("common.enter_continue"))