from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("me/", views.MeView.as_view(), name="me"),
    path("me/avatar/", views.AvatarView.as_view(), name="avatar"),
    path("me/deactivate/", views.DeactivateView.as_view(), name="deactivate"),
    path("me/change-email/", views.ChangeEmailView.as_view(), name="change-email"),
    path(
        "me/social-accounts/",
        views.SocialAccountListView.as_view(),
        name="social-accounts",
    ),
]
