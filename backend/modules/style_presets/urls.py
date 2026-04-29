"""風格預設 URL 路由。"""

from django.urls import path

from .views import StylePresetDetailView, StylePresetListView

urlpatterns = [
    path("", StylePresetListView.as_view(), name="style-preset-list"),
    path("<slug:key>/", StylePresetDetailView.as_view(), name="style-preset-detail"),
]
