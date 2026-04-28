"""通知中心 URL 路由。"""

from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationListView.as_view(), name="notification-list"),
    path("<uuid:pk>/", views.NotificationDetailView.as_view(), name="notification-detail"),
    path("<uuid:pk>/read/", views.NotificationReadView.as_view(), name="notification-read"),
    path("read-all/", views.NotificationReadAllView.as_view(), name="notification-read-all"),
    path(
        "unread-count/",
        views.NotificationUnreadCountView.as_view(),
        name="notification-unread-count",
    ),
    path("preferences/", views.PreferenceListView.as_view(), name="preference-list"),
    path(
        "preferences/<str:category>/",
        views.PreferenceUpdateView.as_view(),
        name="preference-update",
    ),
    path("channels/", views.ChannelListView.as_view(), name="channel-list"),
]
