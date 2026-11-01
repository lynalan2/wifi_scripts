"""Локализация: английский (по умолчанию) и русский, с сохранением выбора.

Выбор языка хранится в ~/.config/wifitool/config.json и переживает перезапуск.
Использование в коде:  from .i18n import t ;  print(t("key", name=x))
Каталог строк — MESSAGES: {"key": ("english", "русский")}.
"""

import json
from pathlib import Path

LANGS = ("en", "ru")
DEFAULT_LANG = "en"
CONFIG_PATH = Path.home() / ".config" / "wifitool" / "config.json"

_lang = None  # кэш выбранного языка


def _read_config():
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_config(cfg):
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception:
        pass


def saved_lang():
    """Язык из конфига или None, если ещё не выбран."""
    lang = _read_config().get("lang")
    return lang if lang in LANGS else None


def current():
    """Текущий язык (кэш -> конфиг -> дефолт)."""
    global _lang
    if _lang is None:
        _lang = saved_lang() or DEFAULT_LANG
    return _lang


def set_lang(lang, persist=True):
    """Устанавливает язык и (по умолчанию) сохраняет в конфиг."""
    global _lang
    if lang not in LANGS:
        return
    _lang = lang
    if persist:
        cfg = _read_config()
        cfg["lang"] = lang
        _write_config(cfg)


def t(key, **kw):
    """Перевод по ключу на текущий язык. Неизвестный ключ -> сам ключ."""
    pair = MESSAGES.get(key)
    if pair is None:
        return key.format(**kw) if kw else key
    s = pair[1] if current() == "ru" else pair[0]
    try:
        return s.format(**kw) if kw else s
    except Exception:
        return s


def choose_language_interactive(first_time=False):
    """Диалог выбора языка. Возвращает выбранный код и сохраняет его."""
    print()
    print("=" * 62)
    print("  Language / Язык")
    print("=" * 62)
    print("  1. English (default)")
    print("  2. Русский")
    cur = current()
    prompt = "Choose / Выберите [1/2]"
    if not first_time:
        prompt += f" (now/сейчас: {cur})"
    prompt += ": "
    while True:
        try:
            c = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            c = ""
        if c in ("", "1", "en", "english"):
            set_lang("en")
            return "en"
        if c in ("2", "ru", "russian", "русский"):
            set_lang("ru")
            return "ru"
        print("  1 = English, 2 = Русский")


# ============================================================================
# Каталог строк. Ключ -> (english, русский). {name} — именованные подстановки.
# ============================================================================

MESSAGES = {
    # ---- общее ----
    "common.enter_continue": ("\nEnter — continue...", "\nEnter — продолжить..."),
    "common.choice": ("Choice: ", "Выбор: "),
    "common.unknown_item": ("Unknown item.", "Неизвестный пункт."),
    "common.cancelled": ("\n[*] Cancelled.", "\n[*] Отменено."),
    "common.interrupted": ("\n[*] Interrupted.", "\n[*] Прервано."),
    "common.back": ("Back", "Назад"),
    "common.yn_prompt": ("Enter Y or N.", "Введите Y или N."),
    "common.need_root": ("[-] Run with sudo.", "[-] Запустите с sudo."),
    "common.tools_missing": ("[-] Missing tools: {tools}", "[-] Не найдены утилиты: {tools}"),

    # ---- главное меню / app ----
    "app.title": ("WiFi Tool", "WiFi Tool"),
    "app.adapter": ("  Adapter:  {v}", "  Адаптер:  {v}"),
    "app.phy": ("  PHY:      {v}", "  PHY:      {v}"),
    "app.mode": ("  Mode:     {v}", "  Режим:    {v}"),
    "app.speed": ("  Speed:    {v}", "  Скорость: {v}"),
    "app.mac": ("  MAC:      {v}", "  MAC:      {v}"),
    "app.grp_adapter": ("  Adapter:", "  Адаптер:"),
    "app.mon_on": ("    1. Enable monitor mode", "    1. Включить режим monitor"),
    "app.managed_on": ("    2. Enable managed mode", "    2. Включить режим managed"),
    "app.change_adapter": ("    0. Change adapter", "    0. Сменить адаптер"),
    "app.language": ("    8. Language / Язык", "    8. Язык / Language"),
    "app.exit": ("    9. Exit", "    9. Выход"),
    "app.need_monitor": ("\n[-] Enable monitor mode first (item 1).",
                         "\n[-] Сначала включите режим monitor (пункт 1)."),
    "app.exit_word": ("\nExit.", "\nВыход."),
    "app.iface_gone": ("[-] Interface {iface} is gone. Choose again.",
                       "[-] Интерфейс {iface} пропал. Выберите снова."),
    "app.ask_restore": ("\n[?] Return {iface} to managed mode before exit?",
                        "\n[?] Вернуть {iface} в режим managed перед выходом?"),
    "app.restoring": ("\n[*] Returning adapter to managed...",
                      "\n[*] Возвращаю адаптер в managed..."),
    "app.left_monitor": ("[*] Adapter left in monitor.",
                         "[*] Адаптер оставлен в monitor."),

    # ---- группы фич в меню ----
    "grp.capture": ("Capture", "Захват"),
    "grp.crack": ("Cracking", "Взлом"),
    "grp.attacks": ("Attacks", "Атаки"),
    "feat.handshake": ("Network analysis (deauth capture)",
                       "Анализ сети (деаутентификация)"),
    "feat.hcxdump": ("Handshake capture (hcxdumptool)",
                     "Захват handshake (hcxdumptool)"),
    "feat.crack": ("Password cracking", "Взлом пароля"),
    "feat.eviltwin": ("Evil Twin (modes: AP / portal / sniffing)",
                      "Evil Twin (меню режимов: AP / портал / sniffing)"),
}
