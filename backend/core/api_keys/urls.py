"""API Key 管理模組路由。"""

from django.urls import path

from . import views

app_name = "api_keys"

urlpatterns = [
    path("", views.APIKeyListCreateView.as_view(), name="list-create"),
    path("<uuid:key_id>/", views.APIKeyDetailView.as_view(), name="detail"),
    path("<uuid:key_id>/revoke/", views.APIKeyRevokeView.as_view(), name="revoke"),
    path("<uuid:key_id>/disable/", views.APIKeyDisableView.as_view(), name="disable"),
    path("<uuid:key_id>/enable/", views.APIKeyEnableView.as_view(), name="enable"),
    path("<uuid:key_id>/rotate/", views.APIKeyRotateView.as_view(), name="rotate"),
    path("<uuid:key_id>/usage/", views.APIKeyUsageView.as_view(), name="usage"),
]
