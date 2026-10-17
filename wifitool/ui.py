"""Хелперы ввода/вывода в консоль: очистка экрана, пауза, вопросы, меню."""

import os


def clear_screen():
    os.system("clear")


def pause(msg="\nEnter — продолжить..."):
    input(msg)


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
        print("Введите Y или N.")


def print_title(title, width=62):
    print("=" * width)
    print(f"  {title}")
    print("=" * width)


def run_menu(title, items, width=62):
    """
    Рисует меню и возвращает выбранный ключ.

    items — список кортежей:
      ("1", "Текст пункта", callable|None)  — пункт действия;
      (None, "Заголовок группы", None)      — подзаголовок секции;
      (None, None, None)                    — пустая строка-разделитель.

    Возвращает строку-ключ, который ввёл пользователь (вызов callable — на стороне вызывающего),
    либо None не возвращает (цикл бесконечный до выбора существующего ключа).
    keys — множество допустимых ключей.
    """
    keys = {key for key, _, _ in items if key is not None}
    while True:
        clear_screen()
        print_title(title, width)
        print()
        for key, text, _ in items:
            if key is None and text is None:
                print()
            elif key is None:
                print(f"  {text}:")
            else:
                print(f"    {key}. {text}")
        print()
        choice = input("Выбор: ").strip()
        if choice in keys:
            return choice
        print("Неизвестный пункт.")
