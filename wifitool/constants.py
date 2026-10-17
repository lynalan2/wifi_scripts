"""Единое место для настроек, путей и списков утилит."""

from pathlib import Path

# ---- Эмуляторы терминала (имя -> базовая команда запуска) ----
# Порядок = приоритет поиска. Добавить новый терминал — одна строка.
TERMINALS = [
    ("xterm",          ["xterm", "-e"]),
    ("qterminal",      ["qterminal", "-e"]),
    ("xfce4-terminal", ["xfce4-terminal", "-e"]),
    ("gnome-terminal", ["gnome-terminal", "--"]),
    ("konsole",        ["konsole", "-e"]),
]

# ---- Диапазоны airodump-ng ----
AIRODUMP_BANDS = "abg"   # 2.4 + 5 ГГц

# ---- Параметры watchdog при захвате handshake ----
WATCHDOG = {
    "check_interval": 5,
    "stale_threshold": 30,
    "cooldown": 20,
    "revive_seconds": 20,
    "startup_grace": 45,
}

# ---- Данные взломщика (hashcat) ----
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "cracker_data"
STATE_FILE = DATA_DIR / "state.json"
WORDLISTS_DIR = DATA_DIR / "wordlists"
CAPTURES_DIR = DATA_DIR / "captures"
SESSIONS_DIR = DATA_DIR / "sessions"

ROCKYOU_URL = (
    "https://github.com/brannondorsey/naive-hashcat/"
    "releases/download/data/rockyou.txt"
)

# ---- Наборы внешних утилит для проверки наличия ----
TOOLS_HANDSHAKE = ("iw", "airodump-ng", "aireplay-ng", "aircrack-ng", "ip")
TOOLS_HCXDUMP = ("hcxdumptool", "hcxpcapngtool", "timeout")

# ---- ANSI-цвета ----
GREEN = "\033[92m"
RESET = "\033[0m"
