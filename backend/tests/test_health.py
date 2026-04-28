import json

from django.test import Client, RequestFactory


def test_health_check_returns_json():
    """測試 health check 回傳 JSON"""
    from config.api_urls import health_check

    factory = RequestFactory()
    request = factory.get("/api/v1/system/health/")
    response = health_check(request)
    assert response.status_code == 200
    data = json.loads(response.content)
    assert "status" in data
    assert "version" in data
    assert "checks" in data


def test_health_check_contains_version():
    """測試 health check 回傳版本資訊"""
    from config.api_urls import health_check

    factory = RequestFactory()
    request = factory.get("/api/v1/system/health/")
    response = health_check(request)
    data = json.loads(response.content)
    assert data["version"] == "0.1.0"


def test_health_check_contains_all_checks():
    """測試 health check 包含所有檢查項目"""
    from config.api_urls import health_check

    factory = RequestFactory()
    request = factory.get("/api/v1/system/health/")
    response = health_check(request)
    data = json.loads(response.content)
    checks = data["checks"]
    assert "database" in checks
    assert "redis" in checks
    assert "celery" in checks


def test_csrf_token_endpoint_returns_token_and_cookie():
    """測試 CSRF 初始化端點會回傳 token 並設定 cookie。"""
    client = Client(enforce_csrf_checks=True)

    response = client.get("/api/v1/system/csrf/")

    assert response.status_code == 200
    data = json.loads(response.content)
    assert "csrf_token" in data
    assert "csrftoken" in response.cookies
    assert response.cookies["csrftoken"].value
    assert isinstance(data["csrf_token"], str)
