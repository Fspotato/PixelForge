"""Agent 生圖 URL 路由。"""

from django.urls import path

from .views import (
    AgentGenerationItemRetryView,
    AgentGenerationSessionApproveView,
    AgentGenerationSessionCancelView,
    AgentGenerationSessionDetailView,
    AgentGenerationSessionDownloadView,
    AgentGenerationSessionListCreateView,
    AgentGenerationSessionMessageView,
)

urlpatterns = [
    path("sessions/", AgentGenerationSessionListCreateView.as_view(), name="agent-session-list"),
    path(
        "sessions/<uuid:session_id>/",
        AgentGenerationSessionDetailView.as_view(),
        name="agent-session-detail",
    ),
    path(
        "sessions/<uuid:session_id>/approve/",
        AgentGenerationSessionApproveView.as_view(),
        name="agent-session-approve",
    ),
    path(
        "sessions/<uuid:session_id>/messages/",
        AgentGenerationSessionMessageView.as_view(),
        name="agent-session-message",
    ),
    path(
        "sessions/<uuid:session_id>/cancel/",
        AgentGenerationSessionCancelView.as_view(),
        name="agent-session-cancel",
    ),
    path(
        "sessions/<uuid:session_id>/download/",
        AgentGenerationSessionDownloadView.as_view(),
        name="agent-session-download",
    ),
    path(
        "items/<uuid:item_id>/retry/",
        AgentGenerationItemRetryView.as_view(),
        name="agent-item-retry",
    ),
]
