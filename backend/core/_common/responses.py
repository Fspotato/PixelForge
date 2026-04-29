"""標準 API 回應格式。"""

from rest_framework import status
from rest_framework.response import Response


class StandardResponse:
    """統一 API 回應格式。"""

    @staticmethod
    def success(
        data=None, message: str = "操作成功", status_code: int = status.HTTP_200_OK, meta=None
    ) -> Response:
        payload = {
            "status": "success",
            "message": message,
            "data": data,
        }
        if meta is not None:
            payload["meta"] = meta
        return Response(payload, status=status_code)

    @staticmethod
    def created(data=None, message: str = "建立成功", meta=None) -> Response:
        return StandardResponse.success(
            data=data,
            message=message,
            status_code=status.HTTP_201_CREATED,
            meta=meta,
        )

    @staticmethod
    def no_content(message: str = "刪除成功") -> Response:
        return Response(
            {
                "status": "success",
                "message": message,
            },
            status=status.HTTP_204_NO_CONTENT,
        )

    @staticmethod
    def error(
        code: str,
        message: str,
        details=None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> Response:
        return Response(
            {
                "status": "error",
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                },
            },
            status=status_code,
        )
