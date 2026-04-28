"""訂閱模組 URL 路由。"""

from django.urls import path

from . import views

app_name = "subscriptions"

urlpatterns = [
    path("", views.SubscriptionListView.as_view(), name="subscription-list"),
    path("create/", views.SubscriptionCreateView.as_view(), name="subscription-create"),
    path("sync-all/", views.SubscriptionSyncAllView.as_view(), name="subscription-sync-all"),
    path("<uuid:pk>/", views.SubscriptionDetailView.as_view(), name="subscription-detail"),
    path("<uuid:pk>/cancel/", views.SubscriptionCancelView.as_view(), name="subscription-cancel"),
    path(
        "<uuid:pk>/terminate/",
        views.SubscriptionTerminateView.as_view(),
        name="subscription-terminate",
    ),
    path("<uuid:pk>/pause/", views.SubscriptionPauseView.as_view(), name="subscription-pause"),
    path("<uuid:pk>/resume/", views.SubscriptionResumeView.as_view(), name="subscription-resume"),
]
