"""操作審計日誌 URL 路由。"""

from django.urls import path

from . import views

app_name = "audit_log"

urlpatterns = [
    path("", views.AuditEntryListView.as_view(), name="list"),
    path("stats/", views.AuditStatsView.as_view(), name="stats"),
    path("export/", views.AuditExportView.as_view(), name="export"),
    path("my/", views.MyAuditLogView.as_view(), name="my"),
    path("<uuid:pk>/", views.AuditEntryDetailView.as_view(), name="detail"),
]
