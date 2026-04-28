"""權限註冊中心 — 模組啟動時註冊權限定義。"""

from core._logger import get_logger

logger = get_logger(__name__)


class PermissionRegistry:
    """權限註冊中心。

    各模組在 AppConfig.ready() 中呼叫 register / register_module 註冊權限，
    再透過 sync_to_database() 同步至資料庫。
    """

    _permissions: dict[str, dict] = {}

    @classmethod
    def register(cls, codename: str, name: str, module: str, description: str = ""):
        """註冊單一權限。"""
        cls._permissions[codename] = {
            "codename": codename,
            "name": name,
            "module": module,
            "description": description,
        }

    @classmethod
    def register_module(cls, module: str, actions: list[tuple[str, str]]):
        """批次註冊模組權限。

        Args:
            module: 模組名稱（例如 "payments"）
            actions: [(action_code, action_name), ...]
                例如 [("view", "檢視"), ("create", "建立")]
        """
        for action_code, action_name in actions:
            codename = f"{module}.{action_code}"
            cls.register(codename, action_name, module)

    @classmethod
    def sync_to_database(cls):
        """將已註冊的權限同步到資料庫。"""
        from .models import Permission

        created_count = 0
        updated_count = 0

        for codename, info in cls._permissions.items():
            _, created = Permission.objects.update_or_create(
                codename=codename,
                defaults={
                    "name": info["name"],
                    "module": info["module"],
                    "description": info["description"],
                    "is_system": True,
                },
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        logger.info(
            "權限同步完成",
            extra={"created": created_count, "updated": updated_count},
        )
        return {"created": created_count, "updated": updated_count}

    @classmethod
    def list_registered(cls) -> list[dict]:
        """列出所有已註冊的權限定義。"""
        return list(cls._permissions.values())

    @classmethod
    def clear(cls):
        """清除所有已註冊的權限（主要用於測試）。"""
        cls._permissions = {}
