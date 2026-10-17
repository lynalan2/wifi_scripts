"""Обёртки над subprocess и проверки окружения (root, наличие утилит)."""

import os
import sys
import shutil
import subprocess


def check_root():
    """Прерывает программу, если запущена не от root."""
    if os.geteuid() != 0:
        print("[-] Запустите с sudo.")
        sys.exit(1)


def missing_tools(tools):
    """Возвращает список утилит из `tools`, которых нет в PATH."""
    return [t for t in tools if shutil.which(t) is None]


def require_tools(tools):
    """Прерывает программу, если каких-то утилит из `tools` нет."""
    missing = missing_tools(tools)
    if missing:
        print(f"[-] Не найдены утилиты: {', '.join(missing)}")
        sys.exit(1)


def run(cmd, **kwargs):
    """subprocess.run с текстом и перехватом вывода по умолчанию."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **kwargs)
