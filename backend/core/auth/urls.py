"""認證模組 URL 路由。"""

from django.urls import path

from . import views

app_name = "auth"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("social/providers/", views.SocialProviderStatusView.as_view(), name="social-providers"),
    path("verify-email/", views.VerifyEmailView.as_view(), name="verify-email"),
    path("password-reset/", views.PasswordResetView.as_view(), name="password-reset"),
    path(
        "password-reset-confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path(
        "social/<str:provider>/start/",
        views.SocialLoginStartView.as_view(),
        name="social-start",
    ),
    path(
        "social/<str:provider>/callback/",
        views.SocialLoginCallbackView.as_view(),
        name="social-callback",
    ),
]
