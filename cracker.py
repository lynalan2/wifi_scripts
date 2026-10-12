#!/usr/bin/env python3
"""
Взлом WPA/WPA2 handshake через hashcat.
Управление cap-файлами, словарями, сессиями и результатами.
"""

import os
import json
import shutil
import signal
import subprocess
import threading
import time
import re
from pathlib import Path

# ============ Пути ============

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "cracker_data"
STATE_FILE = DATA_DIR / "state.json"
WORDLISTS_DIR = DATA_DIR / "wordlists"
CAPTURES_DIR = DATA_DIR / "captures"
SESSIONS_DIR = DATA_DIR / "sessions"

HASHCAT_POTFILE = Path.home() / ".local/share/hashcat/hashcat.potfile"

# ============ Терминал (переиспользуем логику из handshake.py) ============

def find_terminal():
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


def launch_in_terminal(term_name, term_cmd, script_path):
    if term_name == "gnome-terminal":
        launch = term_cmd + ["bash", str(script_path)]
    else:
        launch = term_cmd + [f"bash {script_path}"]
    try:
        return subprocess.Popen(launch, preexec_fn=os.setsid)
    except Exception as e:
        print(f"[!] Не удалось открыть {term_name}: {e}")
        return None


def kill_group(proc):
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
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ============ Управление cap ============

def add_cap(state):
    print("\nВведите путь к .cap файлу:")
    path = input("Путь: ").strip()
    if not path:
        return
    p = Path(path).expanduser()
    if not p.exists():
        print(f"[-] Файл не найден: {p}")
        return
    if p.suffix.lower() != ".cap":
        print("[-] Ожидается файл с расширением .cap")
        return

    name = input("Название (Enter — имя файла): ").strip() or p.stem

    # Конвертируем в .hc22000
    hc22000 = CAPTURES_DIR / f"{p.stem}.hc22000"
    print(f"[*] Конвертирую {p.name} -> {hc22000.name} ...")
    r = subprocess.run(
        ["hcxpcapngtool", "-o", str(hc22000), str(p)],
        capture_output=True, text=True
    )
    if r.returncode != 0 or not hc22000.exists():
        print("[-] Ошибка конвертации:")
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
    print(f"[+] Добавлено: {name}")


def remove_cap(state):
    if not state["caps"]:
        print("[-] Список cap пуст.")
        return
    for i, c in enumerate(state["caps"], 1):
        print(f"  {i}. {c['name']}  [{c['path']}]")
    try:
        idx = int(input("Номер для удаления (0 — отмена): ").strip()) - 1
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
        print(f"[+] Удалено: {c['name']}")


def list_caps(state):
    if not state["caps"]:
        print("[-] Список cap пуст.")
        return
    print("\n{:<4} {:<20} {:<10} {:<8} {}".format(
        "№", "Название", "Прогресс", "Взломан", "Путь"
    ))
    print("-" * 90)
    for i, c in enumerate(state["caps"], 1):
        print("{:<4} {:<20} {:<10} {:<8} {}".format(
            i, c["name"][:18], f"{c.get('progress', 0)}%",
            "да" if c.get("cracked") else "нет", c["path"]
        ))


# ============ Управление словарями ============

def add_wordlist(state):
    print("\nВведите путь к словарю:")
    path = input("Путь: ").strip()
    if not path:
        return
    p = Path(path).expanduser()
    if not p.exists():
        print(f"[-] Файл не найден: {p}")
        return
    name = input("Название (Enter — имя файла): ").strip() or p.stem
    state["wordlists"].append({"path": str(p.resolve()), "name": name})
    save_state(state)
    print(f"[+] Добавлен словарь: {name}")


def remove_wordlist(state):
    if not state["wordlists"]:
        print("[-] Список словарей пуст.")
        return
    for i, w in enumerate(state["wordlists"], 1):
        print(f"  {i}. {w['name']}  [{w['path']}]")
    try:
        idx = int(input("Номер для удаления (0 — отмена): ").strip()) - 1
    except ValueError:
        return
    if 0 <= idx < len(state["wordlists"]):
        w = state["wordlists"].pop(idx)
        save_state(state)
        print(f"[+] Удалён словарь: {w['name']}")


def list_wordlists(state):
    if not state["wordlists"]:
        print("[-] Список словарей пуст.")
        print(f"[*] Положите словарь в {WORDLISTS_DIR} и добавьте его через меню.")
        return
    print("\n{:<4} {:<20} {}".format("№", "Название", "Путь"))
    print("-" * 70)
    for i, w in enumerate(state["wordlists"], 1):
        print("{:<4} {:<20} {}".format(i, w["name"][:18], w["path"]))


def ensure_default_wordlist(state):
    """Если словарей нет — предлагает скачать rockyou."""
    if state["wordlists"]:
        return
    print("\n[!] Нет ни одного словаря.")
    ans = input("Скачать стандартный rockyou.txt? (Y/n): ").strip().lower()
    if ans == 'n':
        return
    dest = WORDLISTS_DIR / "rockyou.txt"
    if not dest.exists():
        print("[*] Скачиваю rockyou.txt (это может занять время)...")
        r = subprocess.run(
            ["wget", "-q", "-O", str(dest),
             "https://github.com/brannondorsey/naive-hashcat/releases/download/data/rockyou.txt"],
            capture_output=True, text=True
        )
        if r.returncode != 0 or not dest.exists():
            print("[-] Не удалось скачать. Добавьте словарь вручную.")
            return
    state["wordlists"].append({"path": str(dest), "name": "rockyou"})
    save_state(state)
    print(f"[+] Добавлен rockyou: {dest}")


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
        print("[-] Незавершённых сессий нет.")
        return
    print("\n{:<4} {:<20} {:<10} {}".format("№", "Название", "Прогресс", "Сессия"))
    print("-" * 70)
    for i, c in enumerate(sessions, 1):
        print("{:<4} {:<20} {:<10} {}".format(
            i, c["name"][:18], f"{c.get('progress', 0)}%", c["session"]
        ))


# ============ Взлом ============

def run_cracking(state):
    if not state["caps"]:
        print("[-] Нет cap-файлов. Сначала добавьте.")
        return
    if not state["wordlists"]:
        print("[-] Нет словарей. Сначала добавьте.")
        return

    # выбор cap
    print("\nВыберите cap для взлома:")
    for i, c in enumerate(state["caps"], 1):
        if c.get("cracked"):
            status = "✓ взломан"
        elif c.get("progress", 0) >= 100:
            status = "словарь исчерпан"
        else:
            status = f"{c.get('progress', 0)}%"
        print(f"  {i}. {c['name']}  [{status}]")
    try:
        idx = int(input("Номер (0 — отмена): ").strip()) - 1
    except ValueError:
        return
    if not (0 <= idx < len(state["caps"])):
        return
    cap = state["caps"][idx]

    if cap.get("cracked"):
        print("[*] Этот cap уже взломан. Смотрите результаты в меню (пункт 9).")
        return

    # выбор словаря
    print("\nВыберите словарь:")
    for i, w in enumerate(state["wordlists"], 1):
        print(f"  {i}. {w['name']}")
    try:
        widx = int(input("Номер (0 — отмена): ").strip()) - 1
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
            for pat in (f"crack_{old_sess}.sh",
                        f"log_{old_sess}.txt",
                        f"out_{old_sess}.txt"):
                try:
                    (DATA_DIR / pat).unlink(missing_ok=True)
                except Exception:
                    pass
        # hashcat restore-файл тоже сносим, чтобы не тянул старую сессию
        for d in (Path.home() / ".local/share/hashcat/sessions",
                  Path.home() / ".hashcat/sessions"):
            try:
                for ext in (".restore", ".log", ".lock"):
                    (d / f"{old_sess}{ext}").unlink(missing_ok=True)
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


    # --- команда hashcat ---
    # potfile выключаем через --potfile-disable, чтобы не пересекаться с чужими сессиями
    common = (
        f'hashcat -m 22000 -a 0 '
        f'--session {session_name} '
        f'--status --status-timer 2 '
        f'--potfile-disable '
        f'-o "{out_file}" '
    )

    if cap.get("progress", 0) > 0:
        # возобновление: hashcat подхватит .restore-файл из ~/.hashcat/sessions/
        hashcat_cmd = f'{common}--restore'
        print(f"[*] Возобновляю сессию {session_name} (было {cap['progress']}%)")
    else:
        hashcat_cmd = f'{common}"{cap["hc22000"]}" "{wordlist["path"]}"'
        print(f"[*] Новая сессия {session_name}")

    # --- bash-обёртка ---
    script_path = DATA_DIR / f"crack_{session_name}.sh"
    script_path.write_text(
        "#!/bin/bash\n"
        f"echo '=== Взлом: {cap['name']} ==='\n"
        f"echo 'Сессия:  {session_name}'\n"
        f"echo 'Словарь: {wordlist['name']}'\n"
        "echo 'Ctrl+C в этом окне — остановить (сессия сохранится).'\n"
        "echo\n"
        f"cd {DATA_DIR}\n"
        # tee: вывод в окно + в файл. -u чтобы не буферизировало
        f"stdbuf -oL -eL {hashcat_cmd} 2>&1 | tee \"{log_file}\"\n"
    )
    script_path.chmod(0o755)

    term_name, term_cmd = find_terminal()
    if term_name is None:
        print("[-] Терминал не найден. Установите xterm: sudo apt install xterm")
        return

    proc = launch_in_terminal(term_name, term_cmd, script_path)
    if proc is None:
        return

    print(f"[*] Взлом запущен в отдельном окне ({term_name}).")
    print("[*] Слежу за прогрессом... (Ctrl+C здесь — остановить)")

    try:
        while proc.poll() is None:
            time.sleep(2)
            new_p = _parse_progress(log_file)
            if new_p > cap.get("progress", 0):
                cap["progress"] = new_p
            if _check_cracked(state, cap, out_file):
                print(f"\n[+] Пароль найден для {cap['name']}!")
                save_state(state)
                kill_group(proc)
                break
            print(f"\r[*] Прогресс: {cap['progress']:3d}%", end="", flush=True)
    except KeyboardInterrupt:
        print("\n[*] Остановка взлома...")
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
        print(f"[+] Готово: {cap['name']} — пароль в пункте 9.")
    else:
        print(f"\n[+] Сессия сохранена: {session_name} ({cap.get('progress', 0)}%)")


def _decode_hashcat_plain(plain):
    """Если hashcat записал $HEX[...] — декодируем обратно в строку."""
    if plain.startswith("$HEX[") and plain.endswith("]"):
        try:
            return bytes.fromhex(plain[5:-1]).decode("utf-8", errors="replace")
        except Exception:
            return plain
    return plain


def _read_hashes(hc22000_file):
    """Возвращает список хешей из .hc22000."""
    try:
        with open(hc22000_file, "r", errors="ignore") as f:
            return [l.strip() for l in f if l.strip()]
    except Exception:
        return []


def _essid_from_hash(h):
    """ESSID из строки WPA*02*MIC*AP*STA*ESSID_HEX*..."""
    try:
        parts = h.split("*")
        if len(parts) > 5 and parts[5]:
            return bytes.fromhex(parts[5]).decode("utf-8", errors="replace")
    except Exception:
        pass
    return None

def list_cracked(state):
    if not state["cracked"]:
        print("[-] Взломанных сетей пока нет.")
        return
    print("\n{:<30} {:<30} {}".format("Сеть (ESSID)", "Пароль", "Cap"))
    print("-" * 80)
    for c in state["cracked"]:
        print("{:<30} {:<30} {}".format(
            str(c["essid"])[:28],
            str(c["password"])[:28],
            str(c["cap"])[:40],
        ))

def _check_cracked(state, cap, out_file):
    """
    Hashcat -m 22000 пишет в out-файл:
        PMK:AP_MAC:STA_MAC:ESSID:password
    Извлекаем ESSID и password, сверяем с .hc22000.
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
        # PMK:AP:STA:ESSID:password  — ровно 5 полей, но пароль может содержать ':'
        parts = line.split(":", 4)
        if len(parts) < 5:
            continue
        essid = parts[3]
        raw_password = parts[4]
        password = _decode_hashcat_plain(raw_password)

        if valid_essids and essid not in valid_essids:
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
            print(f"\n[+] Подобран пароль: {essid} -> {password}")
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
        print("  Взлом пароля (hashcat)")
        print("=" * 62)
        print()
        print("  1. Добавить cap")
        print("  2. Удалить cap")
        print("  3. Просмотр доступных cap")
        print()
        print("  4. Добавить словарь")
        print("  5. Удалить словарь")
        print("  6. Просмотр словарей")
        print()
        print("  7. Начать/продолжить взлом")
        print("  8. Просмотр сессий")
        print("  9. Подобранные пароли")
        print()
        print("  0. Назад")
        print()

        choice = input("Выбор: ").strip()

        if choice == '1':
            add_cap(state)
        elif choice == '2':
            remove_cap(state)
        elif choice == '3':
            list_caps(state)
        elif choice == '4':
            add_wordlist(state)
        elif choice == '5':
            remove_wordlist(state)
        elif choice == '6':
            list_wordlists(state)
        elif choice == '7':
            run_cracking(state)
        elif choice == '8':
            list_sessions(state)
        elif choice == '9':
            list_cracked(state)
        elif choice == '0':
            return
        else:
            print("Неизвестный пункт.")

        input("\nEnter — продолжить...")