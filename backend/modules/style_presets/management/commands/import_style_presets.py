"""匯入 PixelForge 風格預設。"""

from django.core.management.base import BaseCommand

from modules.style_presets.services import StylePresetService


class Command(BaseCommand):
    """將 assets/templates/styles 的風格模板匯入資料庫。"""

    help = "將 PixelForge 風格模板匯入資料庫"

    def handle(self, *args, **options):
        imported_count = StylePresetService.import_templates()
        self.stdout.write(self.style.SUCCESS(f"已匯入 {imported_count} 個風格預設"))
