"""圖片處理 URL 路由。"""

from django.urls import path

from .views import ProcessImageView

urlpatterns = [
    path("jobs/", ProcessImageView.as_view(), name="image-processing-job"),
]
