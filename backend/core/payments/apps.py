from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.payments"
    label = "payments"
    verbose_name = "金流"

    def ready(self):
        """載入事件 Schema 定義並觸發閘道自動註冊。"""
        import core.payments.events  # noqa: F401

        # 載入所有閘道模組，使 @GatewayRegistry.register 裝飾器生效
        import core.payments.gateways.ecpay_gateway  # noqa: F401
        import core.payments.gateways.newebpay_gateway  # noqa: F401
        import core.payments.gateways.stripe_gateway  # noqa: F401
