"""Хелперы ввода/вывода в консоль: очистка экрана, пауза, вопросы, меню."""

import os

from .i18n import t


def clear_screen():
    os.system("clear")


def pause(msg=None):
    input(msg if msg is not None else t("common.enter_continue"))


def ask_int(prompt, default, minimum=1):
    """Спрашивает целое число. Пустой ввод / мусор / слишком маленькое -> default."""
    raw = input(prompt).strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v >= minimum else default
    except ValueError:
        return default


def ask_yes_no(prompt, default=True):
    """Спрашивает да/нет. Пустой ввод -> default. Понимает ru/en."""
    suffix = " (Y/n): " if default else " (y/N): "
    while True:
        ans = input(prompt + suffix).strip().lower()
        if ans == "":
            return default
        if ans in ("y", "yes", "д", "да"):
            return True
        if ans in ("n", "no", "н", "нет"):
            return False
        print(t("common.yn_prompt"))


def print_title(title, width=62):
    print("=" * width)
    print(f"  {title}")
    print("=" * width)
