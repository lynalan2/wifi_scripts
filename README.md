# WiFi Tool

Набор утилит для аудита Wi-Fi: сканирование, захват WPA/WPA2 handshake
(airodump-ng + aireplay-ng и hcxdumptool) и взлом через hashcat.

> Только для легального тестирования сетей, на которые у вас есть разрешение.

## Запуск

```bash
sudo python3 main.py
```

Нужен root. Внешние утилиты: `iw`, `ip`, `airodump-ng`, `aireplay-ng`,
`aircrack-ng`, `hcxdumptool`, `hcxpcapngtool`, `hashcat`, эмулятор терминала
(`xterm` и т.п.).

## Структура

```
main.py                 — точка входа (вызывает wifitool.app.main)
wifitool/
  constants.py   — настройки, пути, списки утилит, параметры watchdog
  system.py      — check_root, require_tools, обёртка subprocess run()
  terminal.py    — запуск bash-скриптов в окнах терминала, гашение процессов
  iface.py       — управление адаптером: режимы, phy, канал, MAC, выбор
  ui.py          — ввод/вывод: меню, вопросы, пауза
  hashfile.py    — разбор .hc22000 и out-файлов hashcat (общий)
  netscan.py     — сканирование сетей (airodump-ng) + разбор CSV
  capture.py     — захват handshake + деаутентификация + watchdog
  hcx.py         — захват handshake/PMKID через hcxdumptool
  cracker.py     — взлом через hashcat (cap/hc22000, словари, сессии)
  menu.py        — реестр действий главного меню (FEATURES)
  app.py         — главный цикл и построение меню
```

Слои зависят «вниз»: feature-модули (`netscan`, `capture`, `hcx`, `cracker`)
опираются на инфраструктуру (`system`, `terminal`, `iface`, `ui`, `hashfile`,
`constants`), а `app`/`menu` их связывают. Инфраструктура не знает о фичах.

## Как добавить новую функцию (пример: Evil Twin)

1. Создайте модуль `wifitool/evil_twin.py` с функцией-сценарием, которая
   принимает имя интерфейса:

   ```python
   # wifitool/evil_twin.py
   from .terminal import find_terminal, launch_in_terminal, kill_group
   from .ui import ask_int, ask_yes_no, pause

   def evil_twin_flow(interface):
       # ... ваша логика (hostapd/dnsmasq/портал и т.д.) ...
       ...
   ```

   Используйте готовую инфраструктуру: терминалы — `terminal`, адаптер —
   `iface`, ввод — `ui`, пути/настройки — `constants`.

2. Зарегистрируйте пункт меню одной строкой в `wifitool/menu.py`:

   ```python
   from .evil_twin import evil_twin_flow
   FEATURES.append(
       Feature("6", "Атаки", "Evil Twin (поддельная точка)",
               evil_twin_flow, needs_monitor=True)
   )
   ```

Меню в главном цикле строится из `FEATURES` автоматически — `main.py` и
`app.py` трогать не нужно. `needs_monitor=True` заставит программу
проверить режим monitor перед запуском.
