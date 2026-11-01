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
    "common.term_open_fail": ("[!] Could not open {term}: {e}",
                              "[!] Не удалось открыть {term}: {e}"),

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

    # ---- capture (handshake) ----
    "cap.win_capture": ("=== Handshake capture: {essid} ({bssid}), channel {ch} ===",
                        "=== Захват handshake: {essid} ({bssid}), канал {ch} ==="),
    "cap.win_stop": ("Ctrl+C — stop capture.", "Ctrl+C — остановить захват."),
    "cap.deauth_title": ("=== Deauthentication ===", "=== Деаутентификация ==="),
    "cap.deauth_target": ("Target (router):", "Цель (роутер):"),
    "cap.deauth_iface": ("Interface:", "Интерфейс:"),
    "cap.deauth_csv": ("Stations CSV:", "CSV станций:"),
    "cap.deauth_stop": ("Ctrl+C — stop.", "Ctrl+C — остановить."),
    "cap.round": ("Round", "Раунд"),
    "cap.phase1": ("Phase 1: broadcast deauth to router",
                   "Фаза 1: broadcast deauth на роутер"),
    "cap.wait8": ("Waiting 8 s for clients to reconnect...",
                  "Ждём 8 сек, чтобы клиенты переподключились..."),
    "cap.no_csv": ("CSV not created yet, repeating broadcast.",
                   "CSV ещё не создан, повторяю broadcast."),
    "cap.no_clients": ("No clients yet. Repeating broadcast.",
                       "Клиентов пока нет. Повторяю broadcast."),
    "cap.clients_found": ("Clients found:", "Обнаружено клиентов:"),
    "cap.phase2": ("Phase 2: targeted deauth ->", "Фаза 2: targeted deauth ->"),
    "cap.round_done": ("All clients processed. New round in 20 s...",
                       "Все клиенты обработаны. Новый раунд через 20 сек..."),
    "cap.revive": ("\n[!] Neither .cap nor .csv updates for >{n} s — "
                   "reviving without channel lock ({r} s).",
                   "\n[!] Ни .cap, ни .csv не обновляются >{n} сек — "
                   "оживляю без фиксации канала ({r} сек)."),
    "cap.revive_done": ("[+] Revive finished.", "[+] Оживление завершено."),
    "cap.bad_channel": ("[-] Invalid channel: {ch}", "[-] Некорректный канал: {ch}"),
    "cap.no_term": ("[!] No terminal found. Capturing here, no window.",
                    "[!] Терминал не найден. Захват в этом окне, без графики."),
    "cap.target": ("\n[*] Target:  {essid} ({bssid}), channel {ch}",
                   "\n[*] Цель:    {essid} ({bssid}), канал {ch}"),
    "cap.file": ("[*] File:    {f}", "[*] Файл:    {f}"),
    "cap.timeout": ("[*] Timeout: {t} s (Ctrl+C to stop)",
                    "[*] Таймаут: {t} сек (Ctrl+C — остановить)"),
    "cap.win_closed": ("\n[*] Capture window closed.", "\n[*] Окно захвата закрыто."),
    "cap.deauth_closed": ("\n[*] Deauth window closed.",
                          "\n[*] Окно деаутентификации закрыто."),
    "cap.found": ("\n[+] Handshake found!", "\n[+] Handshake найден!"),
    "cap.waiting": ("\r[*] Waiting... {r:3d} s", "\r[*] Ожидание... {r:3d} сек"),
    "cap.saved": ("[+] Handshake saved: {f}", "[+] Handshake сохранён: {f}"),
    "cap.not_found": ("[-] Handshake not found. File: {f}",
                      "[-] Handshake не найден. Файл: {f}"),
    "cap.no_file": ("[-] Capture file was not created.",
                    "[-] Файл захвата не создан."),
    "cap.caught": ("\n[+] Handshake caught.", "\n[+] Handshake пойман."),
    "cap.default_path": ("    Default: {p}", "    По умолчанию: {p}"),
    "cap.save_hint": ("    Enter — save to default, 'c' — cancel saving.",
                      "    Enter — сохранить по умолчанию, 'c' — отменить сохранение."),
    "cap.path_prompt": ("Path: ", "Путь: "),
    "cap.mkdir_fail": ("[-] Could not create directory: {e}",
                       "[-] Не удалось создать директорию: {e}"),
    "cap.overwrite": ("'{t}' already exists. Overwrite? (y/n): ",
                      "'{t}' уже существует. Перезаписать? (y/n): "),
    "cap.save_cancel": ("[*] Saving cancelled.", "[*] Сохранение отменено."),
    "cap.actions_title": ("\nActions for the selected network:",
                          "\nДействия с выбранной сетью:"),
    "cap.act_deauth": ("  1. Deauthentication", "  1. Деаутентификация"),
    "cap.act_passive": ("  2. Passive monitoring", "  2. Пассивное наблюдение"),
    "cap.act_back": ("  0. Back", "  0. Назад"),
    "cap.act_prompt": ("Action: ", "Действие: "),
    "cap.act_bad": ("Unknown item. Enter 1, 2 or 0.",
                    "Неизвестный пункт. Введите 1, 2 или 0."),
    "cap.target_line": ("\n[*] Target: {essid} ({bssid})",
                        "\n[*] Цель: {essid} ({bssid})"),
    "cap.back_menu": ("[*] Back to menu.", "[*] Возврат в меню."),
    "cap.ask_timeout": ("\nCapture timeout, seconds (Enter = 180): ",
                        "\nТаймаут захвата в секундах (Enter = 180): "),
    "cap.save_fail": ("[-] Could not save: {e}", "[-] Не удалось сохранить: {e}"),
    "cap.not_saved": ("[*] File not saved.", "[*] Файл не сохранён."),
    "cap.not_caught": ("\n[-] Handshake not caught.", "\n[-] Handshake не пойман."),

    # ---- hcx (hcxdumptool) ----
    "hcx.install": ("    Install: sudo apt install hcxdumptool hcxtools",
                    "    Установите: sudo apt install hcxdumptool hcxtools"),
    "hcx.title": ("\n=== hcxdumptool: handshake/PMKID capture ===",
                  "\n=== hcxdumptool: захват handshake/PMKID ==="),
    "hcx.ask_runs": ("How many scan runs? (Enter = 1): ",
                     "Сколько раз запустить сканирование? (Enter = 1): "),
    "hcx.ask_dur": ("Duration of one run, sec (Enter = 60): ",
                    "Длительность одного прогона, сек (Enter = 60): "),
    "hcx.iface": ("\n[*] Interface: {v}", "\n[*] Интерфейс: {v}"),
    "hcx.runs": ("[*] Runs:      {v}", "[*] Прогонов:  {v}"),
    "hcx.cmd": ("[*] Command:   timeout {d} hcxdumptool -i {i} -w <capture>.pcapng --rds=1",
                "[*] Команда:   timeout {d} hcxdumptool -i {i} -w <capture>.pcapng --rds=1"),
    "hcx.run_hdr": ("  Run {i}/{n}  (timeout {d} s, Ctrl+C — stop run)",
                    "  Прогон {i}/{n}  (timeout {d} сек, Ctrl+C — прервать прогон)"),
    "hcx.run_interrupted": ("\n[*] Run interrupted by user.",
                            "\n[*] Прогон прерван пользователем."),
    "hcx.empty": ("[-] Run {i}: nothing captured (empty pcapng).",
                  "[-] Прогон {i}: ничего не захвачено (pcapng пуст)."),
    "hcx.none_valid": ("[-] Run {i}: no hashcat-valid handshake/PMKID found.",
                       "[-] Прогон {i}: валидных для hashcat handshake/PMKID не найдено."),
    "hcx.run_found": ("[+] Run {i}: networks with a valid hash — {n}:",
                      "[+] Прогон {i}: сетей с валидным хэшем — {n}:"),
    "hcx.dup": ("    - {essid} [{bssid}] {label}: already saved (run {run}), skipping.",
                "    - {essid} [{bssid}] {label}: уже сохранён (прогон {run}), пропускаю."),
    "hcx.save_fail": ("    - {essid} [{bssid}] {label}: [-] cannot save: {e}",
                      "    - {essid} [{bssid}] {label}: [-] не сохранить: {e}"),
    "hcx.saved": ("    - {essid} [{bssid}] {label}: SAVED -> {dest}",
                  "    - {essid} [{bssid}] {label}: СОХРАНЁН -> {dest}"),
    "hcx.summary": ("  SUMMARY", "  ИТОГ"),
    "hcx.sum_none": ("[-] No hashcat-valid handshake/PMKID caught in any run.",
                     "[-] Валидный для hashcat handshake/PMKID не пойман ни в одном прогоне."),
    "hcx.sum_nets": ("[+] Networks with a hashcat-valid hash: {n}",
                     "[+] Сетей с валидным для hashcat хэшем: {n}"),
    "hcx.sum_saved": ("[+] Files saved: {s}  |  duplicates (same net) skipped: {d}",
                      "[+] Сохранено файлов: {s}  |  повторных (та же сеть) пропущено: {d}"),
    "hcx.col_type": ("Type", "Тип"),
    "hcx.col_runs": ("Runs", "Прогоны"),
    "hcx.col_file": ("File", "Файл"),
    "hcx.not_saved": ("(not saved)", "(не сохранён)"),
    "hcx.hint": ("[*] Crack ready .hc22000 directly: hashcat -m 22000 <file> <wordlist>",
                 "[*] Готовые .hc22000 можно сразу перебирать: hashcat -m 22000 <файл> <словарь>"),

    # ---- cracker (hashcat) ----
    "crack.ask_cap": ("\nEnter path to a .cap file:", "\nВведите путь к .cap файлу:"),
    "crack.path": ("Path: ", "Путь: "),
    "crack.file_not_found": ("[-] File not found: {p}", "[-] Файл не найден: {p}"),
    "crack.expect_cap": ("[-] A .cap file is expected", "[-] Ожидается файл с расширением .cap"),
    "crack.ask_name": ("Name (Enter — file name): ", "Название (Enter — имя файла): "),
    "crack.converting": ("[*] Converting {a} -> {b} ...", "[*] Конвертирую {a} -> {b} ..."),
    "crack.conv_err": ("[-] Conversion error:", "[-] Ошибка конвертации:"),
    "crack.added": ("[+] Added: {name}", "[+] Добавлено: {name}"),
    "crack.ask_hc": ("\nPath to a .hc22000 file: ", "\nПуть к .hc22000 файлу: "),
    "crack.expect_hc": ("[-] A .hc22000 file is expected",
                        "[-] Ожидается файл с расширением .hc22000"),
    "crack.not_hc": ("[-] Does not look like hc22000 (no WPA* lines).",
                     "[-] Файл не похож на hc22000 (нет строк WPA*...)."),
    "crack.copy_fail": ("[-] Could not copy: {e}", "[-] Не удалось скопировать: {e}"),
    "crack.added_as": ("[+] Added: {name}  ->  {dest}", "[+] Добавлено: {name}  ->  {dest}"),
    "crack.cap_empty": ("[-] Cap list is empty.", "[-] Список cap пуст."),
    "crack.del_prompt": ("Number to delete (0 — cancel): ",
                         "Номер для удаления (0 — отмена): "),
    "crack.deleted": ("[+] Deleted: {name}", "[+] Удалено: {name}"),
    "crack.col_name": ("Name", "Название"),
    "crack.col_progress": ("Progress", "Прогресс"),
    "crack.col_cracked": ("Cracked", "Взломан"),
    "crack.col_path": ("Path", "Путь"),
    "crack.col_session": ("Session", "Сессия"),
    "crack.yes": ("yes", "да"),
    "crack.no": ("no", "нет"),
    "crack.ask_wl": ("\nEnter path to a wordlist:", "\nВведите путь к словарю:"),
    "crack.wl_added": ("[+] Wordlist added: {name}", "[+] Добавлен словарь: {name}"),
    "crack.wl_empty": ("[-] Wordlist list is empty.", "[-] Список словарей пуст."),
    "crack.wl_deleted": ("[+] Wordlist removed: {name}", "[+] Удалён словарь: {name}"),
    "crack.wl_hint": ("[*] Put a wordlist in {dir} and add it via the menu.",
                      "[*] Положите словарь в {dir} и добавьте его через меню."),
    "crack.no_wl_title": ("\n[!] No wordlists.", "\n[!] Нет ни одного словаря."),
    "crack.ask_rockyou": ("Download the standard rockyou.txt? (Y/n): ",
                          "Скачать стандартный rockyou.txt? (Y/n): "),
    "crack.downloading": ("[*] Downloading rockyou.txt (may take a while)...",
                          "[*] Скачиваю rockyou.txt (это может занять время)..."),
    "crack.dl_fail": ("[-] Download failed. Add a wordlist manually.",
                      "[-] Не удалось скачать. Добавьте словарь вручную."),
    "crack.rockyou_added": ("[+] rockyou added: {dest}", "[+] Добавлен rockyou: {dest}"),
    "crack.no_sessions": ("[-] No unfinished sessions.", "[-] Незавершённых сессий нет."),
    "crack.no_caps": ("[-] No cap files. Add one first.",
                      "[-] Нет cap-файлов. Сначала добавьте."),
    "crack.no_wls": ("[-] No wordlists. Add one first.",
                     "[-] Нет словарей. Сначала добавьте."),
    "crack.pick_cap": ("\nChoose a cap to crack:", "\nВыберите cap для взлома:"),
    "crack.st_cracked": ("✓ cracked", "✓ взломан"),
    "crack.st_exhausted": ("wordlist exhausted", "словарь исчерпан"),
    "crack.num_prompt": ("Number (0 — cancel): ", "Номер (0 — отмена): "),
    "crack.already": ("[*] This cap is already cracked. See results in menu (item 10).",
                      "[*] Этот cap уже взломан. Смотрите результаты в меню (пункт 10)."),
    "crack.pick_wl": ("\nChoose a wordlist:", "\nВыберите словарь:"),
    "crack.resume": ("[*] Resuming session {s} (was {p}%)",
                     "[*] Возобновляю сессию {s} (было {p}%)"),
    "crack.no_restore": ("[!] restore file not found — starting over.",
                         "[!] restore-файл не найден — запускаю сессию заново."),
    "crack.new_session": ("[*] New session {s}", "[*] Новая сессия {s}"),
    "crack.win_title": ("=== Cracking: {name} ===", "=== Взлом: {name} ==="),
    "crack.win_session": ("Session: {s}", "Сессия:  {s}"),
    "crack.win_wl": ("Wordlist: {w}", "Словарь: {w}"),
    "crack.win_stop": ("Ctrl+C in this window — stop (session is saved).",
                       "Ctrl+C в этом окне — остановить (сессия сохранится)."),
    "crack.no_term": ("[-] No terminal found. Install xterm: sudo apt install xterm",
                      "[-] Терминал не найден. Установите xterm: sudo apt install xterm"),
    "crack.started": ("[*] Cracking started in a separate window ({term}).",
                      "[*] Взлом запущен в отдельном окне ({term})."),
    "crack.watching": ("[*] Watching progress... (Ctrl+C here — stop)",
                       "[*] Слежу за прогрессом... (Ctrl+C здесь — остановить)"),
    "crack.pw_found": ("\n[+] Password found for {name}!",
                       "\n[+] Пароль найден для {name}!"),
    "crack.progress": ("\r[*] Progress: {p:3d}%", "\r[*] Прогресс: {p:3d}%"),
    "crack.stopping": ("\n[*] Stopping cracking...", "\n[*] Остановка взлома..."),
    "crack.done": ("[+] Done: {name} — password in item 10.",
                   "[+] Готово: {name} — пароль в пункте 10."),
    "crack.session_saved": ("\n[+] Session saved: {s} ({p}%)",
                            "\n[+] Сессия сохранена: {s} ({p}%)"),
    "crack.none_cracked": ("[-] No cracked networks yet.",
                           "[-] Взломанных сетей пока нет."),
    "crack.col_net": ("Network (ESSID)", "Сеть (ESSID)"),
    "crack.col_pw": ("Password", "Пароль"),
    "crack.pw_got": ("\n[+] Password recovered: {essid} -> {password}",
                     "\n[+] Подобран пароль: {essid} -> {password}"),
    "crack.menu_title": ("Password cracking (hashcat)", "Взлом пароля (hashcat)"),
    "crack.grp_files": ("  Files to crack:", "  Файлы для взлома:"),
    "crack.m_add_cap": ("    1. Add cap (.cap)", "    1. Добавить cap (.cap)"),
    "crack.m_add_hc": ("    2. Add ready .hc22000", "    2. Добавить готовый .hc22000"),
    "crack.m_del_cap": ("    3. Delete cap", "    3. Удалить cap"),
    "crack.m_list_cap": ("    4. List available caps", "    4. Просмотр доступных cap"),
    "crack.grp_wl": ("  Wordlists:", "  Словари:"),
    "crack.m_add_wl": ("    5. Add wordlist", "    5. Добавить словарь"),
    "crack.m_del_wl": ("    6. Delete wordlist", "    6. Удалить словарь"),
    "crack.m_list_wl": ("    7. List wordlists", "    7. Просмотр словарей"),
    "crack.grp_crack": ("  Cracking:", "  Взлом:"),
    "crack.m_run": ("    8. Start/continue cracking", "    8. Начать/продолжить взлом"),
    "crack.m_sessions": ("    9. View sessions", "    9. Просмотр сессий"),
    "crack.m_cracked": ("   10. Recovered passwords", "   10. Подобранные пароли"),
    "crack.m_back": ("    0. Back", "    0. Назад"),

    # ---- evil twin ----
    "et.mode_just_ap": ("Just AP (no portal, no sniffing)",
                        "Just AP (без портала и сниффинга)"),
    "et.mode_captive": ("Captive portal (+ handshake validation)",
                        "Captive portal (+ проверка по handshake)"),
    "et.mode_sniff": ("Sniffing (MITM, internet via uplink + bettercap)",
                      "Sniffing (MITM, интернет через аплинк + bettercap)"),
    "et.mode_sslstrip": ("Sniffing + bettercap sslstrip2 (hstshijack)",
                         "Sniffing + bettercap sslstrip2 (hstshijack)"),
    "et.mode_beef": ("Sniffing + bettercap + BeEF", "Sniffing + bettercap + BeEF"),
    "et.add_path": ("\nPath to your HTML file or template folder: ",
                    "\nПуть к своему HTML-файлу или папке шаблона: "),
    "et.not_found": ("[-] Not found: {src}", "[-] Не найдено: {src}"),
    "et.tpl_name": ("Template name (e.g. altel): ", "Название шаблона (например, altel): "),
    "et.no_index_dir": ("[-] No index.html in the folder.", "[-] В папке нет index.html."),
    "et.expect_html": ("[-] Expected a .html file or a folder with index.html.",
                       "[-] Ожидается .html файл или папка с index.html."),
    "et.tpl_add_fail": ("[-] Could not add template: {e}",
                        "[-] Не удалось добавить шаблон: {e}"),
    "et.tpl_added": ("[+] Template added: {name}  ({path})",
                     "[+] Шаблон добавлен: {name}  ({path})"),
    "et.tpl_hint": ("    Placeholders {{ESSID}}/{{ERROR}}; the form POSTs a 'password' field.",
                    "    Плейсхолдеры {{ESSID}}/{{ERROR}}; форма шлёт POST с полем password."),
    "et.tpl_title": ("\nPortal templates:", "\nШаблоны портала:"),
    "et.tpl_none": ("  (no built-in — add your own)", "  (встроенных нет — добавьте свой)"),
    "et.tpl_add_item": ("  a. Add your own HTML/template", "  a. Добавить свой HTML/шаблон"),
    "et.cancel_item": ("  0. Cancel", "  0. Отмена"),
    "et.tpl_choose": ("Choose template: ", "Выбор шаблона: "),
    "et.tpl_builtin": ("built-in", "встроенный"),
    "et.tpl_custom": ("custom", "свой"),
    "et.mode_title": ("\n=== Evil Twin — choose mode (airgeddon-style) ===",
                      "\n=== Evil Twin — выбор режима (как в airgeddon) ==="),
    "et.mode_back": ("  0. Back", "  0. Назад"),
    "et.mode_prompt": ("Mode: ", "Режим: "),
    "et.no_other_adapters": ("[-] No other Wi-Fi adapters found.",
                             "[-] Других Wi-Fi адаптеров не найдено."),
    "et.pick_attack": ("\nChoose the attack adapter:", "\nВыберите адаптер для атаки:"),
    "et.attack_prompt": ("Attack adapter (0 — no second adapter): ",
                         "Адаптер для атаки (0 — без 2-го адаптера): "),
    "et.enter_num": ("Enter a number.", "Введите число."),
    "et.num_1n": ("Enter a number from 1 to {n}.", "Введите число от 1 до {n}."),
    "et.ask_2nd": ("\n[?] Use a second adapter for the attack (deauth)?",
                   "\n[?] Использовать 2-й адаптер для атаки (деаутентификация)?"),
    "et.deauth_method_title": ("\nDeauth method:", "\nМетод деаутентификации:"),
    "et.method_aireplay": ("aireplay-ng --deauth (standard)",
                           "aireplay-ng --deauth (стандартный)"),
    "et.method_mdk4": ("mdk4 (more aggressive, needs the mdk4 package)",
                       "mdk4 (агрессивнее, нужен пакет mdk4)"),
    "et.method_prompt": ("Method (Enter = 1): ", "Метод (Enter = 1): "),
    "et.no_uplink": ("[-] No internet interface (uplink) found.",
                     "[-] Не найдено интерфейса с интернетом (аплинка)."),
    "et.uplink_title": ("\nInternet interface (shared to the victim), uplink:",
                        "\nИнтерфейс с интернетом (раздаётся жертве), аплинк:"),
    "et.uplink_default": ("  <- default", "  <- по умолчанию"),
    "et.uplink_prompt": ("Uplink (Enter = {d}): ", "Аплинк (Enter = {d}): "),
    "et.need_bettercap": ("[-] Sniffing modes need bettercap: sudo apt install bettercap",
                          "[-] Для sniffing-режимов нужен bettercap: sudo apt install bettercap"),
    "et.need_beef": ("[-] BeEF needs beef-xss: sudo apt install beef-xss",
                     "[-] Для BeEF нужен beef-xss: sudo apt install beef-xss"),
    "et.et_install": ("    Install: sudo apt install hostapd dnsmasq iptables",
                      "    Установите: sudo apt install hostapd dnsmasq iptables"),
    "et.mode_line": ("\n[*] Mode: {mode}.  AP adapter: {ap}",
                     "\n[*] Режим: {mode}.  AP-адаптер: {ap}"),
    "et.hidden_essid": ("[-] Hidden ESSID — the twin needs a name.",
                        "[-] У сети скрытый ESSID — для двойника нужно имя."),
    "et.choose_site": ("\n[*] Choose the twin site for '{essid}'.",
                       "\n[*] Выбор сайта-двойника для '{essid}'."),
    "et.ask_hs": ("\n[?] Validate the password against a handshake (.cap)?",
                  "\n[?] Проверять пароль по handshake (.cap)?"),
    "et.hs_path": ("Path to .cap: ", "Путь к .cap: "),
    "et.hs_missing": ("[!] File not found — no validation.",
                      "[!] Файл не найден — без проверки."),
    "et.no_uplink_mode": ("[-] Sniffing mode is impossible without an uplink.",
                          "[-] Без аплинка sniffing-режим невозможен."),
    "et.deauth_hdr": ("\n[*] Deauthentication of the real network's clients.",
                      "\n[*] Деаутентификация клиентов реальной сети."),
    "et.starting": ("\n[*] Starting Evil Twin...", "\n[*] Запуск Evil Twin..."),
    "et.hostapd_fail": ("[-] hostapd failed to start. Log:",
                        "[-] hostapd не запустился. Лог:"),
    "et.dnsmasq_fail": ("[-] dnsmasq failed to start (port 53 busy?). Log:",
                        "[-] dnsmasq не запустился (занят порт 53?). Лог:"),
    "et.free53": ("    Free 53: sudo systemctl stop systemd-resolved",
                  "    Освободите 53: sudo systemctl stop systemd-resolved"),
    "et.stopping": ("\n[*] Stopping Evil Twin...", "\n[*] Остановка Evil Twin..."),
    "et.error": ("[-] Error: {e}", "[-] Ошибка: {e}"),
    "et.portal_fail": ("[-] Portal failed to start (port {port} busy?).",
                       "[-] Портал не запустился (порт {port} занят?)."),
    "et.bettercap_fail": ("[-] bettercap failed to start. Log:",
                          "[-] bettercap не запустился. Лог:"),
    "et.vif_made": ("[+] Monitor interface {vif} on the same adapter.",
                    "[+] Монитор-интерфейс {vif} на том же адаптере."),
    "et.vif_fail": ("[!] Driver can't do AP+monitor at once — a second adapter is needed.",
                    "[!] Драйвер не поддерживает AP+monitor одновременно — нужен 2-й адаптер."),
    "et.deauth_run": ("[+] Deauthentication ({method}) via {iface} against {bssid}.",
                      "[+] Деаутентификация ({method}) через {iface} по {bssid}."),
    "et.st_running": ("  EVIL TWIN RUNNING  (mode: {mode})",
                      "  EVIL TWIN РАБОТАЕТ  (режим: {mode})"),
    "et.st_twin": ("  Twin network : {essid}  (channel {ch})",
                   "  Сеть-двойник : {essid}  (канал {ch})"),
    "et.st_bssid": ("  Real BSSID   : {bssid}", "  Реальный BSSID: {bssid}"),
    "et.st_ap": ("  AP adapter   : {ap}  ->  {ip}", "  AP-адаптер    : {ap}  ->  {ip}"),
    "et.st_deauth": ("  Deauth       : {method}  ({iface})",
                     "  Деаут         : {method}  ({iface})"),
    "et.st_vif": ("monitor VIF on the same adapter", "монитор-VIF на том же адаптере"),
    "et.st_portal": ("  Portal       : {name}", "  Портал        : {name}"),
    "et.st_check": ("  Password check: {v}", "  Проверка пароля: {v}"),
    "et.st_check_hs": ("by handshake", "по handshake"),
    "et.st_check_no": ("no", "нет"),
    "et.st_uplink": ("  Uplink (net) : {uplink}  (NAT)", "  Аплинк (инет) : {uplink}  (NAT)"),
    "et.st_logs": ("  bettercap logs: in the attack temp folder",
                   "  Логи bettercap: во временной папке атаки"),
    "et.st_stop": ("  Ctrl+C — stop and restore the network.\n",
                   "  Ctrl+C — остановить и вернуть сеть в исходное состояние.\n"),
    "et.proc_stopped": ("[-] Process {key} stopped.", "[-] Процесс {key} остановился."),
    "et.cleanup": ("\n[*] Stopping processes and restoring the network...",
                   "\n[*] Останавливаю процессы и восстанавливаю сеть..."),
    "et.cleanup_done": ("[+] Done, network restored.", "[+] Готово, сеть восстановлена."),
    "et.captured_title": ("  CAPTURED PASSWORDS:", "  СОБРАННЫЕ ПАРОЛИ:"),
    "et.captured_file": ("  File: {f}", "  Файл: {f}"),
    "et.empty": ("  (empty)", "  (пусто)"),

    # ---- portal server ----
    "ps.success_title": ("&#10003; Connection restored",
                         "&#10003; Подключение восстановлено"),
    "ps.success_body": ("Thank you. Connection to {essid} has been restored.",
                        "Спасибо. Соединение с сетью {essid} восстановлено."),
    "ps.success_page_title": ("Done", "Готово"),
    "ps.err_enter": ("Enter the password.", "Введите пароль."),
    "ps.err_wrong": ("Wrong password. Please try again.",
                     "Неверный пароль. Попробуйте ещё раз."),
    "ps.tag_ok": ("OK (matches handshake)", "OK (совпал с handshake)"),
    "ps.tag_bad": ("WRONG (does not match handshake)",
                   "НЕВЕРНЫЙ (не совпал с handshake)"),
    "ps.tag_unchecked": ("not checked", "не проверен"),
    "ps.record": ("[{stamp}] {essid}  password: {pw}  — {tag}",
                  "[{stamp}] {essid}  пароль: {pw}  — {tag}"),
    "ps.write_fail": ("[!] Could not write to creds file: {e}",
                      "[!] Не удалось записать в creds-файл: {e}"),
    "ps.banner_started": ("[*] Portal started on :{port}  (ESSID: {essid})",
                          "[*] Портал запущен на :{port}  (ESSID: {essid})"),
    "ps.banner_hs": ("[*] Passwords validated against handshake: {hs}",
                     "[*] Пароли проверяются по handshake: {hs}"),
    "ps.banner_nohs": ("[*] No handshake set — passwords saved without validation.",
                       "[*] Handshake не задан — пароли сохраняются без проверки."),
    "ps.banner_hint": ("[*] Entered passwords appear below. Ctrl+C to stop.\n",
                       "[*] Введённые пароли появятся ниже. Ctrl+C — остановить.\n"),
}
