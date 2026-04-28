"""金流模組 URL 路由。"""

from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    # 結帳（建立訂單 + 支付）
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    # 付款結果查詢（公開，供付款結果頁呼叫）
    path("result/", views.PaymentResultView.as_view(), name="result"),
    # 訂單
    path("orders/", views.OrderListView.as_view(), name="order-list"),
    path("orders/sync-all/", views.OrderSyncAllView.as_view(), name="order-sync-all"),
    path("orders/<uuid:pk>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<uuid:pk>/retry/", views.OrderRetryView.as_view(), name="order-retry"),
    path("orders/<uuid:pk>/refund/", views.RefundView.as_view(), name="order-refund"),
    # 交易明細
    path("transactions/", views.TransactionListView.as_view(), name="transaction-list"),
    path(
        "transactions/<uuid:pk>/",
        views.TransactionDetailView.as_view(),
        name="transaction-detail",
    ),
    # 閘道
    path("gateways/", views.GatewayListView.as_view(), name="gateway-list"),
    # Webhook
    path("webhook/<str:gateway>/", views.WebhookView.as_view(), name="webhook"),
]
