"""Реестр действий главного меню — ЕДИНАЯ точка расширения.

Чтобы добавить новую функцию:
  1. написать модуль wifitool/<feature>.py с функцией <feature>_flow(interface);
  2. зарегистрировать её здесь одной строкой в FEATURES.
group_key / label_key — ключи из i18n.MESSAGES (меню строится и переводится само).
"""

from dataclasses import dataclass
from typing import Callable

from .capture import handshake_flow
from .hcx import hcxdumptool_flow
from .cracker import cracker_menu
from .evil_twin import evil_twin_flow


@dataclass
class Feature:
    key: str                     # цифра/код пункта (уникальный)
    group_key: str               # i18n-ключ заголовка секции
    label_key: str               # i18n-ключ текста пункта
    run: Callable[[str], None]   # функция вида run(interface)
    needs_monitor: bool = False  # требовать ли monitor перед запуском


# Ключи 1,2 — управление адаптером; 0,8,9 — служебные.
FEATURES = [
    Feature("3", "grp.capture", "feat.handshake", handshake_flow, needs_monitor=True),
    Feature("4", "grp.capture", "feat.hcxdump", hcxdumptool_flow, needs_monitor=True),
    Feature("5", "grp.crack", "feat.crack",
            lambda interface: cracker_menu(), needs_monitor=False),
    # Evil Twin сам управляет режимами адаптера, поэтому needs_monitor=False.
    Feature("6", "grp.attacks", "feat.eviltwin", evil_twin_flow, needs_monitor=False),
]
