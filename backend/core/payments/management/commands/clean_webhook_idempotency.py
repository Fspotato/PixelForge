"""清理過期的 Webhook 冪等性紀錄。"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.payments.models import WebhookIdempotencyKey


class Command(BaseCommand):
    help = "清理超過指定天數的已完成 Webhook 冪等性紀錄"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="保留天數（預設 90 天）",
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = WebhookIdempotencyKey.objects.filter(
            processed_at__lt=cutoff,
            status="completed",
        ).delete()
        self.stdout.write(self.style.SUCCESS(f"已清理 {deleted} 筆過期冪等紀錄（{days} 天前）"))
