"""Реестр действий главного меню — ЕДИНАЯ точка расширения.

Чтобы добавить новую функцию (например, evil twin):
  1. написать модуль wifitool/evil_twin.py с функцией evil_twin_flow(interface);
  2. зарегистрировать её здесь одной строкой в FEATURES (см. пример внизу).
Больше ничего в main.py/app.py править не нужно — меню построится само.
"""

from dataclasses import dataclass
from typing import Callable

from .capture import handshake_flow
from .hcx import hcxdumptool_flow
from .cracker import cracker_menu


@dataclass
class Feature:
    """Пункт меню-действие.

    key          — цифра/код пункта (уникальный);
    group        — заголовок секции в меню («Захват», «Взлом», ...);
    label        — текст пункта;
    run          — функция вида run(interface);
    needs_monitor— требовать ли режим monitor перед запуском.
    """
    key: str
    group: str
    label: str
    run: Callable[[str], None]
    needs_monitor: bool = False


# Реестр функций главного меню. Порядок = порядок в меню.
# Ключи 1,2 зарезервированы под управление адаптером, 0 и 9 — служебные.
FEATURES = [
    Feature("3", "Захват", "Анализ сети (деаутентификация)",
            handshake_flow, needs_monitor=True),
    Feature("4", "Захват", "Захват handshake (hcxdumptool)",
            hcxdumptool_flow, needs_monitor=True),
    Feature("5", "Взлом", "Взлом пароля",
            lambda interface: cracker_menu(), needs_monitor=False),
]


# --- Пример: как добавить evil twin (раскомментировать и дописать модуль) ---
# from .evil_twin import evil_twin_flow
# FEATURES.append(
#     Feature("6", "Атаки", "Evil Twin (поддельная точка)",
#             evil_twin_flow, needs_monitor=True)
# )
