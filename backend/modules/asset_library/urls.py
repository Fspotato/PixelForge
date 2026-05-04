"""資產庫 URL 路由。"""

from django.urls import path

from .views import (
    AssetDetailView,
    AssetImageView,
    AssetListView,
    AssetMetadataView,
    AssetRetryView,
)

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
    path(
        "<uuid:asset_id>/origin/",
        AssetImageView.as_view(),
        {"image_type": "origin"},
        name="asset-origin",
    ),
    path("<uuid:asset_id>/metadata/", AssetMetadataView.as_view(), name="asset-metadata"),
    path("<uuid:asset_id>/retry/", AssetRetryView.as_view(), name="asset-retry"),
]
