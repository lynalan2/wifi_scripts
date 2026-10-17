"""wifitool — набор Wi-Fi утилит (захват handshake, hcxdumptool, взлом).

Пакет разбит по слоям:
  constants  — все настройки и пути в одном месте;
  system     — обёртки над subprocess, проверки root/утилит;
  terminal   — запуск bash-скриптов в отдельных окнах, гашение процессов;
  iface      — управление Wi-Fi адаптером (режимы, канал, phy);
  ui         — ввод/вывод в консоль (меню, вопросы, пауза);
  hashfile   — разбор .hc22000 / out-файлов hashcat (общий для cracker и hcx);
  netscan    — сканирование сетей через airodump-ng;
  capture    — захват handshake + деаутентификация + watchdog;
  hcx        — захват через hcxdumptool;
  cracker    — взлом через hashcat;
  menu       — реестр действий главного меню (точка расширения);
  app        — главный цикл программы.

Как добавить новую функцию (например, evil twin): см. README.md.
"""
