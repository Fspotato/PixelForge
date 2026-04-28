"""共用 ViewSet 基底。"""

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from core._logger import get_logger

from .pagination import StandardPagination
from .responses import StandardResponse


class BaseViewSet(viewsets.GenericViewSet):
    """框架級 ViewSet 基底。"""

    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    @property
    def logger(self):
        return get_logger(self.__class__.__module__)

    def get_standard_response(self, data=None, message: str = "操作成功", **kwargs):
        return StandardResponse.success(data=data, message=message, **kwargs)


class BaseModelViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    mixins.ListModelMixin,
    BaseViewSet,
):
    """提供完整 CRUD 操作的 ViewSet 基底。"""


class ReadOnlyBaseViewSet(
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    BaseViewSet,
):
    """提供唯讀操作的 ViewSet 基底。"""