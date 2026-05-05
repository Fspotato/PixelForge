"""自訂認證後端 — 支援 email 或使用者名稱進行認證。"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q

User = get_user_model()


class EmailBackend(ModelBackend):
    """以 email 或使用者名稱進行認證的後端。"""

    def authenticate(
        self,
        request,
        username=None,
        email=None,
        password=None,
        identifier=None,
        **kwargs,
    ):
        lookup_value = (
            identifier
            or email
            or username
            or kwargs.get(User.USERNAME_FIELD)
            or ""
        ).strip()
        if not lookup_value or password is None:
            return None

        try:
            user = User.objects.get(
                Q(email__iexact=lookup_value) | Q(username__iexact=lookup_value)
            )
        except User.DoesNotExist:
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
