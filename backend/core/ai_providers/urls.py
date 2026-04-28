"""AI 供應商模組 URL 路由。"""

from django.urls import path

from . import views

app_name = "ai_providers"

urlpatterns = [
    path("chat/", views.ChatCompletionView.as_view(), name="chat"),
    path("embeddings/", views.EmbeddingView.as_view(), name="embeddings"),
    path("models/", views.ModelListView.as_view(), name="models"),
    path("providers/", views.ProviderListView.as_view(), name="providers"),
    path("usage/", views.UsageView.as_view(), name="usage"),
    path("test-config/", views.AiTestConfigView.as_view(), name="test-config"),
    path("image/generate/", views.ImageGenerateView.as_view(), name="image-generate"),
]
