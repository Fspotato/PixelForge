"""Agent 生圖 API。"""

from django.http import HttpResponse
from rest_framework.views import APIView

from core._common import StandardResponse

from .serializers import (
    AgentGenerationMessageCreateSerializer,
    AgentGenerationSessionCreateSerializer,
    AgentGenerationSessionSerializer,
    AgentGenerationSessionSummarySerializer,
)
from .services import AgentGenerationService


class AgentGenerationSessionListCreateView(APIView):
    """列出與建立聊天式 Agent Session。"""

    def get(self, request):
        sessions = AgentGenerationService.list_user_sessions(user=request.user)
        serializer = AgentGenerationSessionSummarySerializer(sessions, many=True)
        return StandardResponse.success(
            data=serializer.data, message="取得 Agent 生圖 Session 成功"
        )

    def post(self, request):
        serializer = AgentGenerationSessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = AgentGenerationService.create_session(
            user=request.user,
            data=serializer.validated_data,
        )
        return StandardResponse.created(
            data=AgentGenerationSessionSerializer(session).data,
            message="Agent 對話已建立",
        )


class AgentGenerationSessionDetailView(APIView):
    """取得 Agent 生圖 Session 詳情。"""

    def get(self, request, session_id):
        session = AgentGenerationService.get_user_session(user=request.user, session_id=session_id)
        serializer = AgentGenerationSessionSerializer(session)
        return StandardResponse.success(
            data=serializer.data, message="取得 Agent 生圖 Session 成功"
        )


class AgentGenerationSessionMessageView(APIView):
    """在既有 Agent Session 中新增一則聊天訊息。"""

    def post(self, request, session_id):
        serializer = AgentGenerationMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = AgentGenerationService.add_message(
            user=request.user,
            session_id=session_id,
            message=serializer.validated_data["message"],
            client_message_id=serializer.validated_data.get("client_message_id", ""),
            auto_generate=serializer.validated_data.get("auto_generate"),
        )
        return StandardResponse.success(data=AgentGenerationSessionSerializer(session).data)


class AgentGenerationSessionApproveView(APIView):
    """相容舊端點：在對話資訊完整後啟動生成。"""

    def post(self, request, session_id):
        session = AgentGenerationService.approve_session(user=request.user, session_id=session_id)
        serializer = AgentGenerationSessionSerializer(session)
        return StandardResponse.success(data=serializer.data, message="Agent 生圖已開始")


class AgentGenerationSessionCancelView(APIView):
    """取消 Agent 生圖 Session。"""

    def post(self, request, session_id):
        session = AgentGenerationService.cancel_session(user=request.user, session_id=session_id)
        serializer = AgentGenerationSessionSerializer(session)
        return StandardResponse.success(data=serializer.data, message="Agent 生圖已取消")


class AgentGenerationSessionDownloadView(APIView):
    """下載單一 Agent Session 的所有完成素材。"""

    def get(self, request, session_id):
        archive_name, archive_bytes = AgentGenerationService.download_session_archive(
            user=request.user,
            session_id=session_id,
        )
        response = HttpResponse(archive_bytes, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{archive_name}"'
        return response


class AgentGenerationItemRetryView(APIView):
    """重試單一 Agent 生圖項目。"""

    def post(self, request, item_id):
        session = AgentGenerationService.retry_item(user=request.user, item_id=item_id)
        serializer = AgentGenerationSessionSerializer(session)
        return StandardResponse.success(data=serializer.data, message="Agent 生圖項目已重試")
