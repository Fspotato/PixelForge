"""Logger handlers。"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path


class DailyFileHandler(logging.Handler):
    """依日期切分檔名的 file handler。"""

    def __init__(
        self,
        directory: str,
        filename_prefix: str,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.directory = Path(directory)
        self.filename_prefix = filename_prefix
        self.encoding = encoding
        self._current_date: date | None = None
        self._file_handler: logging.FileHandler | None = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._ensure_handler()
            if self._file_handler is None:
                return
            self._file_handler.emit(record)
        except Exception:
            self.handleError(record)

    def setFormatter(self, fmt: logging.Formatter | None) -> None:
        super().setFormatter(fmt)
        if self._file_handler is not None:
            self._file_handler.setFormatter(fmt)

    def flush(self) -> None:
        if self._file_handler is not None:
            self._file_handler.flush()

    def close(self) -> None:
        try:
            if self._file_handler is not None:
                self._file_handler.close()
                self._file_handler = None
        finally:
            super().close()

    def after_fork(self) -> None:
        """Fork 後重置 file handler，避免子程序繼承已關閉的 fd。"""
        if self._file_handler is not None:
            self._file_handler = None
            self._current_date = None

    def _ensure_handler(self) -> None:
        current_date = self._today()
        # 若日期未變則不重建（無論 _file_handler 是 None 或已開啟）
        if self._current_date == current_date:
            return

        if self._file_handler is not None:
            self._file_handler.close()
            self._file_handler = None

        try:
            file_path = self._build_file_path(current_date)
            self.directory.mkdir(parents=True, exist_ok=True)
            self._file_handler = logging.FileHandler(file_path, encoding=self.encoding)
            self._file_handler.setLevel(self.level)
            if self.formatter is not None:
                self._file_handler.setFormatter(self.formatter)
        except OSError:
            # fork 後子程序可能無法開啟同一個已被主程序持有的檔案
            # （如 Docker bind-mount on Windows 的強制鎖定語意）
            # 靜默略過，此程序的日誌僅輸出至 console
            self._file_handler = None
        finally:
            # 無論成功或失敗都更新日期，避免每次 emit 都重試
            self._current_date = current_date

    def _build_file_path(self, current_date: date) -> Path:
        return self.directory / f"{self.filename_prefix}-{current_date.isoformat()}.log"

    def _today(self) -> date:
        return datetime.now().date()


__all__ = ["DailyFileHandler"]
