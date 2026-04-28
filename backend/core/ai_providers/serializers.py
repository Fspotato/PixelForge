"""AI 供應商模組序列化器。"""

from __future__ import annotations

from rest_framework import serializers

from core._common.base_serializers import BaseSerializer


class MessageSerializer(BaseSerializer):
    """聊天訊息序列化器。"""

    role = serializers.ChoiceField(choices=["system", "user", "assistant"])
    content = serializers.CharField()


class ChatRequestSerializer(BaseSerializer):
    """聊天請求序列化器。"""

    provider = serializers.CharField(required=False, allow_blank=True, default="")
    model = serializers.CharField()
    messages = MessageSerializer(many=True)
    temperature = serializers.FloatField(default=0.7, min_value=0.0, max_value=2.0)
    max_tokens = serializers.IntegerField(required=False, allow_null=True, default=None)
    stream = serializers.BooleanField(default=False)


class EmbeddingRequestSerializer(BaseSerializer):
    """嵌入請求序列化器。"""

    provider = serializers.CharField(required=False, allow_blank=True, default="")
    model = serializers.CharField()
    texts = serializers.ListField(child=serializers.CharField(), min_length=1)


class ProviderConfigSerializer(BaseSerializer):
    """供應商配置序列化器。"""

    provider_name = serializers.CharField(max_length=50)
    api_key = serializers.CharField(write_only=True)
    default_model = serializers.CharField(required=False, allow_blank=True, default="")
    fallback_provider = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(default=True)


class ImageGenerateRequestSerializer(BaseSerializer):
    """圖像生成請求序列化器。"""

    provider = serializers.CharField(required=False, allow_blank=True, default="")
    model = serializers.CharField()
    prompt = serializers.CharField()
    n = serializers.IntegerField(default=1, min_value=1, max_value=4)
    size = serializers.CharField(default="1024x1024")
