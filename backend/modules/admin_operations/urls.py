"""管理操作 URL 路由。"""

from django.urls import path

from .views import (
    AdminAssetDeleteView,
    AdminAssetListView,
    AdminGenerationJobCancelView,
    AdminGenerationJobListView,
    DashboardView,
)

urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="admin-dashboard"),
    path(
        "generation-jobs/", AdminGenerationJobListView.as_view(), name="admin-generation-job-list"
    ),
    path(
        "generation-jobs/<uuid:job_id>/cancel/",
        AdminGenerationJobCancelView.as_view(),
        name="admin-generation-job-cancel",
    ),
    path("assets/", AdminAssetListView.as_view(), name="admin-asset-list"),
    path("assets/<uuid:asset_id>/", AdminAssetDeleteView.as_view(), name="admin-asset-delete"),
]
