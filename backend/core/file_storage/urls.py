"""檔案儲存服務 URL 路由。"""

from django.urls import path

from . import views

app_name = "file_storage"

urlpatterns = [
    path("upload/", views.FileUploadView.as_view(), name="upload"),
    path("presign/", views.FilePresignView.as_view(), name="presign"),
    path("<uuid:pk>/confirm/", views.FileConfirmView.as_view(), name="confirm"),
    path("<uuid:pk>/", views.FileDetailView.as_view(), name="detail"),
    path("<uuid:pk>/download/", views.FileDownloadView.as_view(), name="download"),
    path("quota/", views.StorageQuotaView.as_view(), name="quota"),
    path("backends/", views.StorageBackendListView.as_view(), name="backends"),
    path("", views.FileListView.as_view(), name="list"),
]
