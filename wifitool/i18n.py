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

    # ---- iface ----
    "iface.unknown": ("Unknown", "Неизвестно"),
    "iface.not_found": ("[-] Interface {iface} not found.",
                        "[-] Интерфейс {iface} не найден."),
    "iface.already_monitor": ("[+] {iface} is already in monitor mode.",
                              "[+] {iface} уже в режиме monitor."),
    "iface.switching_monitor": ("[*] {iface} ({phy}): switching {cur} -> monitor",
                                "[*] {iface} ({phy}): переключаю {cur} -> monitor"),
    "iface.now_monitor": ("[+] {iface} switched to monitor.",
                          "[+] {iface} переведён в monitor."),
    "iface.mode_after": ("[-] Mode after switch: {mode}. Expected monitor.",
                         "[-] Режим после переключения: {mode}. Ожидался monitor."),
    "iface.no_monitor_support": ("[*] The adapter driver may not support monitor mode.",
                                 "[*] Драйвер адаптера может не поддерживать monitor mode."),
    "iface.switch_error": ("[-] Switch error: {e}", "[-] Ошибка переключения: {e}"),
    "iface.now_managed": ("[+] {iface} returned to managed.",
                          "[+] {iface} возвращён в managed."),
    "iface.managed_fail": ("[-] Could not return to managed: {e}",
                           "[-] Не удалось вернуть managed: {e}"),
    "iface.to_monitor": ("[*] Switching {iface} to monitor",
                         "[*] Перевод {iface} в monitor"),
    "iface.done": ("[+] Done.", "[+] Готово."),
    "iface.switch_fail": ("[-] Could not switch mode: {e}",
                          "[-] Не удалось переключить режим: {e}"),
    "iface.restoring_managed": ("[*] Returning {iface} to managed...",
                                "[*] Возвращаю {iface} в managed..."),
    "iface.none_found": ("[-] No Wi-Fi interfaces found (iw dev is empty).",
                         "[-] Не найдено ни одного Wi-Fi интерфейса (iw dev пуст)."),
    "iface.none_hint": ("    Check: lsusb, rfkill list, dmesg | tail",
                        "    Проверь: lsusb, rfkill list, dmesg | tail"),
    "iface.available": ("\nAvailable Wi-Fi adapters:", "\nДоступные Wi-Fi адаптеры:"),
    "iface.ask_number": ("\nEnter adapter number (0 — exit): ",
                         "\nВведите номер адаптера (0 — выход): "),
    "iface.err_range": ("Error: enter a number from 1 to {n}.",
                        "Ошибка: введите число от 1 до {n}."),
    "iface.err_int": ("Error: an integer is required.",
                      "Ошибка: нужно ввести целое число."),

    # ---- netscan ----
    "common.hidden": ("<hidden>", "<скрытая>"),
    "scan.none": ("[-] No networks found.", "[-] Сети не найдены."),
    "scan.col_enc": ("Encryption", "Шифрование"),
    "scan.duration_title": ("\nScan duration:", "\nВремя сканирования:"),
    "scan.duration_inf": ("  Enter or 0 — unlimited (Ctrl+C to stop) [default]",
                          "  Enter или 0 — бесконечно (Ctrl+C для остановки) [по умолчанию]"),
    "scan.duration_sec": ("  Or a number of seconds", "  Или число секунд"),
    "scan.duration_bad": ("[-] Invalid. Using unlimited mode.",
                          "[-] Некорректно. Использую бесконечный режим."),
    "scan.pick": ("\nPick a network number (1-{n}, 0 — cancel): ",
                  "\nВыберите номер сети (1-{n}, 0 — отмена): "),
    "scan.empty_input": ("Empty input. Enter a number or 0 to cancel.",
                         "Пустой ввод. Введите число или 0 для отмены."),
    "scan.err_0n": ("Error: integer from 0 to {n} required.",
                    "Ошибка: нужно целое число от 0 до {n}."),
    "scan.err_1n": ("Error: the number must be from 1 to {n}.",
                    "Ошибка: число должно быть от 1 до {n}."),
    "scan.term_fail": ("[!] Could not open {term}: {e}",
                       "[!] Не удалось открыть {term}: {e}"),
    "scan.no_term": ("[!] No terminal found, scanning here.",
                     "[!] Терминал не найден, запускаю сканирование здесь же."),
    "scan.running_inf": ("[*] Scanning... Ctrl+C to stop.",
                         "[*] Сканирование... Ctrl+C — остановить."),
    "scan.running_sec": ("[*] Scanning {d} s (Ctrl+C to stop).",
                         "[*] Сканирование {d} сек (Ctrl+C — остановить)."),
    "scan.remaining": ("\r[*] Remaining: {r:3d} s",
                       "\r[*] Осталось: {r:3d} сек"),
    "scan.stopped": ("\n[*] Stopped.", "\n[*] Остановлено."),
    "scan.total": ("[+] Networks found: {n}", "[+] Итого найдено сетей: {n}"),
    "scan.win_title": ("Scanning 2.4 + 5 GHz. Ctrl+C to stop.",
                       "Сканирование 2.4 + 5 ГГц. Ctrl+C — остановить."),
}
