"""JWT 認證 — 優先讀取 Authorization header，否則退回 HttpOnly cookie。"""

from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import TokenError


class CookieJWTAuthentication(JWTAuthentication):
    """支援 Bearer 與 HttpOnly cookie 的 JWT 認證。"""

    def authenticate(self, request):
        header = self.get_header(request)
        raw_token = None

        if header is not None:
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None
        else:
            raw_token = request.COOKIES.get(settings.JWT_AUTH_COOKIE)
            if raw_token is None:
                return None
            try:
                validated_token = self.get_validated_token(raw_token)
                return self.get_user(validated_token), validated_token
            except (AuthenticationFailed, TokenError):
                return None

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token
