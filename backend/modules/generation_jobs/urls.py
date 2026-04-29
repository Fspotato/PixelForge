"""生成任務 URL 路由。"""

from django.urls import path

from .views import (
    GenerationJobCancelView,
    GenerationJobDetailView,
    GenerationJobListCreateView,
    GenerationJobProgressView,
)

urlpatterns = [
    path("", GenerationJobListCreateView.as_view(), name="generation-job-list-create"),
    path("<uuid:job_id>/", GenerationJobDetailView.as_view(), name="generation-job-detail"),
    path(
        "<uuid:job_id>/progress/",
        GenerationJobProgressView.as_view(),
        name="generation-job-progress",
    ),
    path("<uuid:job_id>/cancel/", GenerationJobCancelView.as_view(), name="generation-job-cancel"),
]
