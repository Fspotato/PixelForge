"""audit_log 模組單元測試。"""

from datetime import timedelta

import pytest
from django.utils import timezone

from core._event_bus.envelope import EventEnvelope
from core.accounts.models import User
from core.audit_log.models import AuditCategory, AuditEntry, AuditSeverity
from core.audit_log.serializers import AuditEntrySerializer, AuditStatsSerializer
from core.audit_log.services import AuditService, compute_changes, sanitize_payload

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def user():
    """建立測試用使用者。"""

    return User.objects.create_user(email="test@example.com", password="testpass123")


def create_entry(**overrides):
    """建立預設審計記錄。"""

    data = {
        "event_type": "auth.user.logged_in",
        "category": AuditCategory.AUTH,
        "severity": AuditSeverity.INFO,
        "description": "測試事件",
        "actor_id": "actor-1",
        "actor_email": "actor@example.com",
        "actor_ip": "127.0.0.1",
        "actor_user_agent": "pytest",
        "resource_type": "accounts.user",
        "resource_id": "user-1",
        "action": "logged_in",
        "changes": {},
        "payload": {"note": "ok"},
        "request_id": "req-1",
        "source_event_id": "evt-1",
    }
    data.update(overrides)
    return AuditEntry.objects.create(**data)


def test_audit_entry_creation_records_all_fields(user):
    entry = create_entry(actor_id=str(user.id), actor_email=user.email, resource_id=str(user.id))

    assert entry.event_type == "auth.user.logged_in"
    assert entry.category == AuditCategory.AUTH
    assert entry.actor_email == user.email
    assert entry.payload == {"note": "ok"}
    assert entry.request_id == "req-1"


def test_audit_entry_rejects_updates():
    entry = create_entry(description="初始描述")
    entry.description = "應該失敗的修改"

    with pytest.raises(ValueError, match="不可修改"):
        entry.save()


def test_audit_entry_rejects_delete():
    entry = create_entry()

    with pytest.raises(ValueError, match="不可刪除"):
        entry.delete()


def test_audit_entry_str_representation():
    entry = create_entry(actor_email="hero@example.com", category=AuditCategory.AUTH)

    assert str(entry) == "[auth] auth.user.logged_in by hero@example.com"


def test_audit_entry_meta_configuration():
    meta = AuditEntry._meta
    index_fields = {tuple(index.fields) for index in meta.indexes}

    assert meta.app_label == "audit_log"
    assert meta.ordering == ["-created_at"]
    assert ("actor_id", "-created_at") in index_fields
    assert ("resource_type", "resource_id") in index_fields
    assert ("category", "-created_at") in index_fields
    assert ("event_type", "-created_at") in index_fields


def test_audit_service_log_sanitizes_payload():
    entry = AuditService.log(
        event_type="auth.user.logged_in",
        category=AuditCategory.AUTH,
        action="logged_in",
        actor_email="audit@example.com",
        payload={
            "password": "secret",
            "nested": {"token": "abc", "visible": "value"},
        },
    )

    assert entry.actor_email == "audit@example.com"
    assert entry.payload["password"] == "***"
    assert entry.payload["nested"]["token"] == "***"
    assert entry.payload["nested"]["visible"] == "value"


def test_audit_service_log_persists_changes():
    changes = {"name": {"old": "舊值", "new": "新值"}}
    entry = AuditService.log(
        event_type="accounts.profile.updated",
        category=AuditCategory.ACCOUNT,
        action="profile_updated",
        changes=changes,
    )

    assert entry.changes == changes


def test_audit_service_log_from_event_creates_entry():
    payload = {
        "user_id": "user-42",
        "actor_email": "member@example.com",
        "actor_ip": "10.0.0.1",
        "changes": {"field": {"old": 1, "new": 2}},
    }
    event = EventEnvelope(event_type="auth.user.logged_in", payload=payload)
    event.actor_id = "user-42"
    event.request_id = "req-evt"

    entry = AuditService.log_from_event(event)

    assert entry is not None
    assert entry.resource_type == "accounts.user"
    assert entry.resource_id == "user-42"
    assert entry.action == "logged_in"
    assert entry.actor_email == "member@example.com"
    assert entry.request_id == "req-evt"


def test_audit_service_log_from_event_ignores_unknown_events():
    event = EventEnvelope(event_type="unknown.event", payload={})

    assert AuditService.log_from_event(event) is None
    assert AuditEntry.objects.count() == 0


def test_audit_service_query_filters_by_action():
    entry_login = AuditService.log(
        event_type="auth.user.logged_in",
        category=AuditCategory.AUTH,
        action="logged_in",
    )
    AuditService.log(
        event_type="auth.user.logged_out",
        category=AuditCategory.AUTH,
        action="logged_out",
    )

    results = AuditService.query(action="logged_in")

    assert list(results) == [entry_login]


def test_audit_service_query_filters_by_actor(user):
    target = AuditService.log(
        event_type="auth.user.logged_in",
        category=AuditCategory.AUTH,
        action="logged_in",
        actor_id=str(user.id),
    )
    AuditService.log(
        event_type="auth.user.logged_in",
        category=AuditCategory.AUTH,
        action="logged_in",
        actor_id="other-user",
    )

    results = AuditService.query(actor_id=str(user.id))

    assert list(results) == [target]


def test_audit_service_query_filters_by_date_range():
    older = AuditService.log(
        event_type="auth.user.logged_in",
        category=AuditCategory.AUTH,
        action="logged_in",
    )
    newer = AuditService.log(
        event_type="auth.user.logged_in",
        category=AuditCategory.AUTH,
        action="logged_in",
    )
    older_timestamp = timezone.now() - timedelta(days=5)
    AuditEntry.objects.filter(pk=older.pk).update(created_at=older_timestamp)

    cutoff = timezone.now() - timedelta(days=2)
    results = AuditService.query(date_from=cutoff)

    assert list(results) == [newer]


def test_audit_service_get_stats_returns_expected_structure():
    AuditService.log(
        event_type="auth.user.logged_in",
        category=AuditCategory.AUTH,
        action="logged_in",
        severity=AuditSeverity.INFO,
    )
    critical_entry = AuditService.log(
        event_type="security.alert.triggered",
        category=AuditCategory.SECURITY,
        action="alert_triggered",
        severity=AuditSeverity.CRITICAL,
        description="關鍵提醒",
        actor_email="sec@example.com",
    )

    stats = AuditService.get_stats()

    assert stats["total"] == 2
    assert stats["today_count"] == 2
    assert stats["by_category"]["auth"] == 1
    assert stats["by_category"]["security"] == 1
    assert stats["by_severity"]["info"] == 1
    assert stats["by_severity"]["critical"] == 1
    assert stats["recent_critical"][0]["event_type"] == critical_entry.event_type


def test_sanitize_payload_masks_sensitive_fields():
    payload = {
        "password": "abc123",
        "token": "secret-token",
        "nested": {"secret": "value", "safe": "ok"},
    }

    sanitized = sanitize_payload(payload)

    assert sanitized["password"] == "***"
    assert sanitized["token"] == "***"
    assert sanitized["nested"]["secret"] == "***"
    assert sanitized["nested"]["safe"] == "ok"


def test_compute_changes_detects_differences():
    old = {"name": "Alice", "email": "old@example.com"}
    new = {"name": "Bob", "email": "old@example.com", "role": "admin"}

    changes = compute_changes(old, new)

    assert changes["name"] == {"old": "Alice", "new": "Bob"}
    assert changes["role"] == {"old": None, "new": "admin"}
    assert "email" not in changes


def test_audit_entry_serializer_outputs_expected_fields(user):
    entry = create_entry(actor_id=str(user.id), actor_email=user.email, resource_id=str(user.id))

    data = AuditEntrySerializer(entry).data

    assert data["id"] == str(entry.id)
    assert data["actor_email"] == user.email
    assert data["resource_id"] == str(user.id)
    assert data["action"] == "logged_in"
    assert data["event_type"] == "auth.user.logged_in"


def test_audit_stats_serializer_validates_payload_structure():
    payload = {
        "total": 3,
        "today_count": 2,
        "by_category": {"auth": 2, "security": 1},
        "by_severity": {"info": 2, "critical": 1},
        "recent_critical": [
            {
                "id": "evt-1",
                "event_type": "security.alert.triggered",
                "description": "告警",
                "actor_email": "sec@example.com",
                "created_at": timezone.now().isoformat(),
            }
        ],
    }

    serializer = AuditStatsSerializer(data=payload)

    assert serializer.is_valid()
    assert serializer.validated_data == payload
