"""Обёртки над subprocess и проверки окружения (root, наличие утилит)."""

import os
import sys
import shutil
import subprocess

from .i18n import t


def check_root():
    """Прерывает программу, если запущена не от root."""
    if os.geteuid() != 0:
        print(t("common.need_root"))
        sys.exit(1)


def missing_tools(tools):
    """Возвращает список утилит из `tools`, которых нет в PATH."""
    return [tool for tool in tools if shutil.which(tool) is None]


def require_tools(tools):
    """Прерывает программу, если каких-то утилит из `tools` нет."""
    missing = missing_tools(tools)
    if missing:
        print(t("common.tools_missing", tools=", ".join(missing)))
        sys.exit(1)


def run(cmd, **kwargs):
    """subprocess.run с текстом и перехватом вывода по умолчанию."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    return subprocess.run(cmd, **kwargs)
