"""API Keys 模組單元測試。"""

import hashlib
from unittest.mock import patch

import pytest
from rest_framework.exceptions import AuthenticationFailed

from core.accounts.models import User
from core.api_keys.authentication import APIKeyAuthentication
from core.api_keys.key_generator import KeyGenerator
from core.api_keys.models import APIKey, APIKeyStatus, APIKeyUsageLog
from core.api_keys.scope import ScopeChecker
from core.api_keys.serializers import APIKeyCreateSerializer, APIKeyResponseSerializer
from core.api_keys.services import APIKeyService

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(
        email="api@example.com",
        password="testpass123",
        is_active=True,
    )


def test_key_generator_generate_format():
    full_key, prefix, key_hash = KeyGenerator.generate()

    assert full_key.startswith("ask_")
    assert prefix == full_key[:8]
    assert len(key_hash) == 64


def test_key_generator_generate_unique_keys():
    keys = {KeyGenerator.generate()[0] for _ in range(3)}

    assert len(keys) == 3


def test_key_generator_hash_key():
    key = "ask_demo_key"
    expected = hashlib.sha256(key.encode()).hexdigest()

    assert KeyGenerator.hash_key(key) == expected


def test_key_generator_verify_success():
    key = "ask_demo_key"
    hash_value = KeyGenerator.hash_key(key)

    assert KeyGenerator.verify(key, hash_value) is True


def test_key_generator_verify_fail():
    key = "ask_demo_key"
    hash_value = KeyGenerator.hash_key(key)

    assert KeyGenerator.verify("ask_other_key", hash_value) is False


def test_scope_checker_exact_match():
    assert ScopeChecker.check(["payments.view"], "payments.view") is True


def test_scope_checker_module_wildcard():
    assert ScopeChecker.check(["payments.*"], "payments.refund") is True


def test_scope_checker_denied():
    assert ScopeChecker.check(["reports.*"], "payments.view") is False


def test_api_key_model_creation(user):
    api_key = APIKey.objects.create(
        owner=user,
        name="主要金鑰",
        key_prefix="ask_1234",
        key_hash=KeyGenerator.hash_key("ask_1234_full"),
        scopes=["payments.view"],
    )

    assert api_key.owner == user
    assert api_key.is_valid is True


def test_api_key_usage_log_uses_bigautofield(user):
    api_key = APIKey.objects.create(
        owner=user,
        name="記錄金鑰",
        key_prefix="ask_log",
        key_hash=KeyGenerator.hash_key("ask_log_full"),
    )
    log = APIKeyUsageLog.objects.create(
        api_key=api_key,
        endpoint="/payments/",
        method="GET",
        status_code=200,
        ip_address="127.0.0.1",
        user_agent="pytest",
    )

    assert isinstance(log.id, int)
    assert log.id > 0


def test_api_key_service_create_returns_full_key(user):
    with patch("core.api_keys.services.publish_event"):
        api_key, raw_key = APIKeyService.create(user, name="建立測試")

    assert api_key.owner == user
    assert raw_key.startswith("ask_")
    assert api_key.key_prefix == raw_key[:8]


def test_api_key_service_revoke(user):
    api_key, _ = APIKeyService.create(user, name="撤銷測試")

    with patch("core.api_keys.services.publish_event"):
        revoked = APIKeyService.revoke(api_key.id, user)

    assert revoked.status == APIKeyStatus.REVOKED
    assert revoked.revoked_at is not None


def test_api_key_service_disable_enable(user):
    api_key, _ = APIKeyService.create(user, name="停用測試")

    with patch("core.api_keys.services.publish_event"):
        disabled = APIKeyService.disable(api_key.id, user)
        enabled = APIKeyService.enable(api_key.id, user)

    assert disabled.status == APIKeyStatus.DISABLED
    assert enabled.status == APIKeyStatus.ACTIVE


def test_api_key_service_rotate(user):
    old_key, _ = APIKeyService.create(user, name="輪換測試")

    with patch("core.api_keys.services.publish_event"):
        new_key, new_raw = APIKeyService.rotate(old_key.id, user)

    old_key.refresh_from_db()

    assert new_key.owner == user
    assert new_raw.startswith("ask_")
    assert old_key.status == APIKeyStatus.REVOKED
    assert old_key.replaced_by == new_key


def test_api_key_authentication_success(user, rf):
    api_key, raw_key = APIKeyService.create(user, name="認證成功")
    request = rf.get("/api/")
    request.META[APIKeyAuthentication.HEADER_NAME] = raw_key

    backend = APIKeyAuthentication()
    user_obj, key_obj = backend.authenticate(request)

    assert user_obj == user
    assert key_obj == api_key


def test_api_key_authentication_invalid_key(rf):
    request = rf.get("/api/")
    request.META[APIKeyAuthentication.HEADER_NAME] = "ask_invalid"
    backend = APIKeyAuthentication()

    with pytest.raises(AuthenticationFailed):
        backend.authenticate(request)


def test_api_key_authentication_revoked_key(user, rf):
    api_key, raw_key = APIKeyService.create(user, name="撤銷驗證")
    api_key.status = APIKeyStatus.REVOKED
    api_key.save(update_fields=["status"])
    request = rf.get("/api/")
    request.META[APIKeyAuthentication.HEADER_NAME] = raw_key

    backend = APIKeyAuthentication()

    with pytest.raises(AuthenticationFailed):
        backend.authenticate(request)


def test_api_key_create_serializer_validation():
    serializer = APIKeyCreateSerializer(
        data={
            "name": "建立金鑰",
            "description": "建立序列化器測試",
            "scopes": ["payments.view"],
            "rate_limit": 50,
        }
    )

    assert serializer.is_valid() is True


def test_api_key_response_serializer_excludes_full_key(user):
    api_key, _ = APIKeyService.create(user, name="回應序列化")

    data = APIKeyResponseSerializer(api_key).data

    assert data["key_prefix"] == api_key.key_prefix
    assert "full_key" not in data
