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
  evil_twin.py   — поддельная точка доступа + captive-портал
  portal_server.py    — веб-сервер портала (запускается отдельным процессом)
  portal_templates/   — встроенные HTML-шаблоны портала
  menu.py        — реестр действий главного меню (FEATURES)
  app.py         — главный цикл и построение меню
```

Слои зависят «вниз»: feature-модули (`netscan`, `capture`, `hcx`, `cracker`)
опираются на инфраструктуру (`system`, `terminal`, `iface`, `ui`, `hashfile`,
`constants`), а `app`/`menu` их связывают. Инфраструктура не знает о фичах.

## Evil Twin (пункт меню 6)

Подменю режимов, как в airgeddon. Нужны `hostapd`, `dnsmasq`, `iptables`;
для sniffing-режимов ещё `bettercap`, для BeEF — `beef-xss`.

Режимы:
1. **Just AP** — открытый двойник + деаут, без портала и перехвата.
2. **Captive portal** — портал с вводом пароля Wi-Fi, весь HTTP заворачивается
   на него; введённый пароль можно сверять с пойманным handshake (aircrack-ng).
   Выбор шаблона: встроенный `default` или **свой HTML** (пункт «a» — `.html`
   файл или папка с `index.html`; так делается копия страницы оператора, напр. Altel).
3. **Sniffing** — MITM: жертве даётся реальный интернет через **аплинк** (NAT),
   а трафик снифается bettercap.
4. **Sniffing + sslstrip2** — то же + bettercap sslstrip/hstshijack.
5. **Sniffing + BeEF** — то же + внедрение BeEF-хука в HTTP-страницы.

Общее: скан и выбор цели, выбор метода деаута (`aireplay-ng` или `mdk4`),
выбор числа адаптеров:
- **1 адаптер** — на том же радио создаётся виртуальный monitor-интерфейс
  (`iw ... interface add ... type monitor`, как в airgeddon), через него идёт
  deauth на канале цели (= канал AP). Нужен драйвер с поддержкой AP+monitor;
- **2 адаптера** — 1-й держит AP, 2-й независимо шлёт deauth (нужен, если
  драйвер не умеет AP+monitor или нужен deauth на другом канале).

Для sniffing-режимов (3–5) машине нужен отдельный выход в интернет (аплинк:
ethernet/3-й адаптер) — он раздаётся жертве через NAT, иначе жертва заметит
отсутствие интернета. Собранные порталом пароли — в `evil_twin_data/captured.txt`;
логи bettercap/beef — во временной папке атаки. По Ctrl+C всё
останавливается, iptables/ip_forward/режимы адаптеров восстанавливаются.
4. (опционально) проверка введённого пароля по заранее пойманному handshake
   (`.cap`) через aircrack-ng — неверные пароли портал отклоняет и просит ещё раз.

Собранные пароли печатаются вживую и пишутся в `evil_twin_data/captured.txt`.
По Ctrl+C всё останавливается и сеть/iptables восстанавливаются.

Сеть-двойник всегда **открытая** (без пароля) — иначе жертва не смогла бы
подключиться без ключа; в airgeddon captive-портал работает так же.

Если телефон подключается, но плашка «Вход в сеть» не появляется:
- порт 53 занят — `dnsmasq` не поднимется (скрипт это сообщит); освободите:
  `sudo systemctl stop systemd-resolved`;
- политика iptables INPUT = DROP резала DNS/HTTP до портала — теперь скрипт сам
  ставит INPUT/OUTPUT/FORWARD ACCEPT и явно пропускает 53/67/80 на AP;
- на телефоне включён **Private DNS (DNS-over-TLS)** — он идёт мимо нашего
  dnsmasq, портал не сработает; выключите его в настройках Wi-Fi телефона.

### Контракт HTML-шаблона портала

- файл называется `index.html` (если добавляете папкой — положите его туда);
- плейсхолдеры: `{{ESSID}}` (имя сети) и `{{ERROR}}` (блок ошибки при неверном
  пароле) подставляются сервером;
- форма шлёт `POST` (на `/` или любой путь), поле пароля называется `password`
  (также принимаются `pass`/`pwd`/`key`/`psk`/`wifi_password`);
- рядом можно класть css/js/картинки — сервер отдаёт статику из папки шаблона.

## Как добавить новую функцию (общий рецепт)

Evil Twin выше сделан ровно по этому шаблону — повторите для своей функции:

1. Создайте модуль `wifitool/<feature>.py` с функцией-сценарием, принимающей
   имя интерфейса:

   ```python
   # wifitool/myfeature.py
   from .terminal import find_terminal, launch_in_terminal, kill_group
   from .ui import ask_int, ask_yes_no, pause

   def myfeature_flow(interface):
       ...
   ```

   Используйте готовую инфраструктуру: терминалы — `terminal`, адаптер —
   `iface`, ввод — `ui`, пути/настройки — `constants`, разбор хэшей — `hashfile`.

2. Зарегистрируйте пункт меню одной строкой в `wifitool/menu.py`:

   ```python
   from .myfeature import myfeature_flow
   FEATURES.append(
       Feature("7", "Атаки", "Моя функция", myfeature_flow, needs_monitor=True)
   )
   ```

Меню в главном цикле строится из `FEATURES` автоматически — `main.py` и
`app.py` трогать не нужно. `needs_monitor=True` заставит программу
проверить режим monitor перед запуском (если функция сама управляет
режимами, ставьте `False`, как в Evil Twin).
