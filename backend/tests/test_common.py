"""_common 模組單元測試。"""

from __future__ import annotations

import pytest
from django.db import connection, models
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from core._common.base_models import BaseModel
from core._common.exception_handler import global_exception_handler
from core._common.exceptions import ServiceError
from core._common.pagination import StandardPagination
from core._common.responses import StandardResponse

pytestmark = pytest.mark.django_db(transaction=True)


class CommonTestModel(BaseModel):
    """提供 _common 測試使用的具體 model。"""

    name = models.CharField(max_length=50)

    class Meta:
        app_label = "tests"
        db_table = "tests_common_test_model"


@pytest.fixture
def common_test_model_table():
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(CommonTestModel)
    yield CommonTestModel
    with connection.schema_editor() as schema_editor:
        schema_editor.delete_model(CommonTestModel)


def test_timestamp_mixin_auto_sets_timestamps(common_test_model_table):
    instance = common_test_model_table.objects.create(name="timestamp")

    assert instance.created_at is not None
    assert instance.updated_at is not None


def test_soft_delete_and_restore(common_test_model_table):
    instance = common_test_model_table.objects.create(name="soft-delete")

    instance.delete()

    assert common_test_model_table.objects.count() == 0
    deleted_instance = common_test_model_table.all_objects.get(pk=instance.pk)
    assert deleted_instance.is_deleted is True
    assert deleted_instance.deleted_at is not None

    deleted_instance.restore()

    restored_instance = common_test_model_table.objects.get(pk=instance.pk)
    assert restored_instance.is_deleted is False
    assert restored_instance.deleted_at is None


def test_standard_response_formats():
    success_response = StandardResponse.success(data={"value": 1}, meta={"page": 1})
    created_response = StandardResponse.created(data={"id": 1})
    no_content_response = StandardResponse.no_content()
    error_response = StandardResponse.error(
        code="TEST_ERROR",
        message="測試失敗",
        details={"field": ["required"]},
    )

    assert success_response.status_code == status.HTTP_200_OK
    assert success_response.data == {
        "status": "success",
        "message": "操作成功",
        "data": {"value": 1},
        "meta": {"page": 1},
    }
    assert created_response.status_code == status.HTTP_201_CREATED
    assert created_response.data["message"] == "建立成功"
    assert no_content_response.status_code == status.HTTP_204_NO_CONTENT
    assert no_content_response.data is None
    assert error_response.status_code == status.HTTP_400_BAD_REQUEST
    assert error_response.data == {
        "status": "error",
        "error": {
            "code": "TEST_ERROR",
            "message": "測試失敗",
            "details": {"field": ["required"]},
        },
    }


def test_global_exception_handler_handles_service_error():
    response = global_exception_handler(
        ServiceError(code="SERVICE_ERROR", message="業務錯誤", details={"scope": "test"}),
        {},
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {
        "status": "error",
        "error": {
            "code": "SERVICE_ERROR",
            "message": "業務錯誤",
            "details": {"scope": "test"},
        },
    }


def test_global_exception_handler_handles_drf_validation_error():
    response = global_exception_handler(DRFValidationError({"name": ["此欄位為必填"]}), {})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data == {
        "status": "error",
        "error": {
            "code": "API_ERROR",
            "message": "資料驗證失敗",
            "details": {"name": ["此欄位為必填"]},
        },
    }


def test_global_exception_handler_handles_unexpected_error():
    response = global_exception_handler(RuntimeError("boom"), {})

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert response.data == {
        "status": "error",
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "伺服器內部錯誤",
            "details": None,
        },
    }


def test_standard_pagination_response_format():
    paginator = StandardPagination()
    factory = APIRequestFactory()
    request = Request(factory.get("/items/", {"page": 2, "page_size": 2}))
    data = [1, 2, 3, 4, 5]

    page = paginator.paginate_queryset(data, request)
    response = paginator.get_paginated_response(page)

    assert response.status_code == status.HTTP_200_OK
    assert response.data == {
        "status": "success",
        "data": [3, 4],
        "meta": {
            "page": 2,
            "page_size": 2,
            "total": 5,
            "total_pages": 3,
            "has_next": True,
            "has_previous": True,
        },
    }
