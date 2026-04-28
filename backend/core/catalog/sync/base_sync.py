"""商品目錄同步基底類別。"""

from abc import ABC, abstractmethod


class BaseCatalogSync(ABC):
    """商品目錄同步基底類別。"""

    provider_name: str = ""

    @abstractmethod
    def sync(self, dry_run=False, deactivate_missing=False):
        """執行同步。回傳 dict: {items_synced, items_created, items_updated}"""
        ...
