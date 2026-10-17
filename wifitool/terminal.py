"""Запуск bash-скриптов в отдельных окнах терминала и гашение процессов.

Единое место для всей работы с терминалами — раньше это было скопировано
в handshake.py и cracker.py.
"""

import os
import signal
import subprocess
from pathlib import Path

from .constants import TERMINALS


def find_terminal():
    """Ищет доступный эмулятор терминала. Возвращает (имя, базовую команду) или (None, None)."""
    import shutil
    for name, cmd in TERMINALS:
        if shutil.which(name):
            return name, cmd
    return None, None


def write_script(path, body):
    """Пишет исполняемый bash-скрипт по пути `path`."""
    path = Path(path)
    path.write_text(body)
    path.chmod(0o755)
    return path


def launch_in_terminal(term_name, term_cmd, script_path):
    """Запускает bash-скрипт в окне терминала. Возвращает Popen или None."""
    if term_name == "gnome-terminal":
        launch = term_cmd + ["bash", str(script_path)]
    else:
        # xterm, konsole, qterminal, xfce4-terminal — хотят одну строку
        launch = term_cmd + [f"bash {script_path}"]
    try:
        return subprocess.Popen(launch, preexec_fn=os.setsid)
    except Exception as e:
        print(f"[!] Не удалось открыть {term_name}: {e}")
        return None


def run_script(script_path):
    """find_terminal + launch_in_terminal. Возвращает (proc|None, term_name|None)."""
    term_name, term_cmd = find_terminal()
    if term_name is None:
        return None, None
    return launch_in_terminal(term_name, term_cmd, script_path), term_name


def kill_group(proc):
    """Корректно гасит группу процессов (терминал + его дети): SIGINT, затем SIGKILL."""
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
