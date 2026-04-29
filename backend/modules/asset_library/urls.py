"""資產庫 URL 路由。"""

from django.urls import path

from .views import AssetDetailView, AssetImageView, AssetListView, AssetRetryView

urlpatterns = [
    path("", AssetListView.as_view(), name="asset-list"),
    path("<uuid:asset_id>/", AssetDetailView.as_view(), name="asset-detail"),
    path(
        "<uuid:asset_id>/thumbnail/",
        AssetImageView.as_view(),
        {"image_type": "thumbnail"},
        name="asset-thumbnail",
    ),
    path(
        "<uuid:asset_id>/image/",
        AssetImageView.as_view(),
        {"image_type": "image"},
        name="asset-image",
    ),
    path("<uuid:asset_id>/retry/", AssetRetryView.as_view(), name="asset-retry"),
]
