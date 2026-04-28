"""商品目錄同步管理指令。

用法：
    python manage.py sync_catalog --provider stripe
    python manage.py sync_catalog --provider stripe --dry-run
    python manage.py sync_catalog --provider stripe --deactivate-missing
"""

from django.core.management.base import BaseCommand

from core._event_bus import publish_event


class Command(BaseCommand):
    help = "從外部閘道同步商品目錄"

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            choices=["stripe"],
            required=True,
            help="同步來源閘道名稱",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="僅模擬同步，不寫入資料庫",
        )
        parser.add_argument(
            "--deactivate-missing",
            action="store_true",
            default=False,
            help="停用閘道端已不存在的商品",
        )

    def handle(self, *args, **options):
        provider = options["provider"]
        dry_run = options["dry_run"]
        deactivate_missing = options["deactivate_missing"]

        self.stdout.write(f"開始同步商品目錄（來源：{provider}）...")

        syncer = self._get_syncer(provider)
        result = syncer.sync(dry_run=dry_run, deactivate_missing=deactivate_missing)

        if not dry_run:
            publish_event(
                "catalog.sync.completed",
                {
                    "provider": provider,
                    "items_synced": result["items_synced"],
                    "items_created": result["items_created"],
                    "items_updated": result["items_updated"],
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"同步完成 — 總計: {result['items_synced']}, "
                f"新增: {result['items_created']}, "
                f"更新: {result['items_updated']}"
            )
        )

    def _get_syncer(self, provider: str):
        """根據 provider 名稱取得對應的同步類別實例。"""
        if provider == "stripe":
            from core.catalog.sync.stripe_sync import StripeCatalogSync

            return StripeCatalogSync()

        raise ValueError(f"不支援的同步來源：{provider}")
