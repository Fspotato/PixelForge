#!/usr/bin/env python
"""Django 管理指令入口。"""

import os
import sys


def main():
    """執行 Django 管理指令。"""
    os.environ.setdefault(
        "DJANGO_SETTINGS_MODULE",
        os.getenv("DJANGO_SETTINGS_MODULE", "config.settings.dev"),
    )
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "無法匯入 Django。請確認 Django 已安裝，且 PYTHONPATH 設定正確。"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
