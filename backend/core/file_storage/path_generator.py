"""檔案路徑生成器 — 產生使用者隔離的唯一儲存路徑。"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime


class PathGenerator:
    """檔案儲存路徑生成器。

    產生格式：{user_id}/{folder?}/{YYYY-MM}/{unique_name}{ext}
    """

    @staticmethod
    def generate(user_id: str, folder: str, filename: str) -> str:
        """產生唯一儲存路徑。

        Args:
            user_id: 使用者 ID。
            folder: 資料夾名稱（可為空）。
            filename: 原始檔案名稱。

        Returns:
            以 ``/`` 分隔的儲存路徑。
        """
        ext = os.path.splitext(filename)[1].lower()
        date_prefix = datetime.now(UTC).strftime("%Y-%m")
        unique_name = uuid.uuid4().hex[:16]
        parts = [str(user_id)]
        if folder:
            parts.append(folder)
        parts.extend([date_prefix, f"{unique_name}{ext}"])
        return "/".join(parts)
