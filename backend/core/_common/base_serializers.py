"""共用 Serializer 基底。"""

from rest_framework import serializers


class BaseSerializer(serializers.Serializer):
    """提供共用 serializer 輔助屬性。"""

    @property
    def current_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)


class BaseModelSerializer(serializers.ModelSerializer):
    """提供共用 model serializer 輔助屬性。"""

    @property
    def current_user(self):
        request = self.context.get("request")
        return getattr(request, "user", None)