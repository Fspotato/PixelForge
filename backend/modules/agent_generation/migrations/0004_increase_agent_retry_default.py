"""提高 Agent 項目預設自動重試次數。"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_generation", "0003_agentgenerationmessage_client_message_id_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentgenerationsession",
            name="max_retry_per_item",
            field=models.PositiveSmallIntegerField(default=3, verbose_name="項目最大重試次數"),
        ),
    ]
