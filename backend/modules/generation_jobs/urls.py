"""生成任務 URL 路由。"""

from django.urls import path

from .views import (
    GenerationJobCancelView,
    GenerationJobDetailView,
    GenerationJobHistoryDetailView,
    GenerationJobHistoryListView,
    GenerationJobListCreateView,
    GenerationJobLiveListView,
    GenerationJobProgressView,
)

urlpatterns = [
    path("", GenerationJobListCreateView.as_view(), name="generation-job-list-create"),
    path("live/", GenerationJobLiveListView.as_view(), name="generation-job-live-list"),
    path("history/", GenerationJobHistoryListView.as_view(), name="generation-job-history-list"),
    path("<uuid:job_id>/", GenerationJobDetailView.as_view(), name="generation-job-detail"),
    path(
        "<uuid:job_id>/history/",
        GenerationJobHistoryDetailView.as_view(),
        name="generation-job-history-detail",
    ),
    path(
        "<uuid:job_id>/progress/",
        GenerationJobProgressView.as_view(),
        name="generation-job-progress",
    ),
    path("<uuid:job_id>/cancel/", GenerationJobCancelView.as_view(), name="generation-job-cancel"),
]
