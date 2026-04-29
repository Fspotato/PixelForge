"""_task_queue 模組單元測試。"""

from unittest.mock import MagicMock, patch

from core._task_queue.models import TaskStatus, TaskType
from core._task_queue.retry_policies import RetryPolicy

# ── RetryPolicy 測試（純邏輯，不需 DB） ──────────────────────────


class TestRetryPolicyExponentialBackoff:
    """測試指數退避策略。"""

    def test_retries_0(self):
        assert RetryPolicy.exponential_backoff(0) == 60

    def test_retries_1(self):
        assert RetryPolicy.exponential_backoff(1) == 120

    def test_retries_2(self):
        assert RetryPolicy.exponential_backoff(2) == 240

    def test_retries_5_capped_by_max_delay(self):
        # 60 * 2^5 = 1920，未超過 max_delay=3600
        assert RetryPolicy.exponential_backoff(5) == 1920

    def test_capped_at_max_delay(self):
        # 60 * 2^10 = 61440 → 應被限制為 3600
        assert RetryPolicy.exponential_backoff(10) == 3600

    def test_custom_base_and_max(self):
        assert RetryPolicy.exponential_backoff(3, base_delay=10, max_delay=100) == 80
        assert RetryPolicy.exponential_backoff(4, base_delay=10, max_delay=100) == 100


class TestRetryPolicyFixedDelay:
    """測試固定延遲策略。"""

    def test_default_delay(self):
        assert RetryPolicy.fixed_delay() == 60

    def test_custom_delay(self):
        assert RetryPolicy.fixed_delay(120) == 120

    def test_always_same_value(self):
        val = RetryPolicy.fixed_delay(30)
        for _ in range(5):
            assert RetryPolicy.fixed_delay(30) == val


class TestRetryPolicyLinearBackoff:
    """測試線性退避策略。"""

    def test_retries_0(self):
        assert RetryPolicy.linear_backoff(0) == 60

    def test_retries_1(self):
        assert RetryPolicy.linear_backoff(1) == 120

    def test_retries_2(self):
        assert RetryPolicy.linear_backoff(2) == 180

    def test_custom_base_delay(self):
        assert RetryPolicy.linear_backoff(3, base_delay=10) == 40


# ── Model 枚舉測試（不需 DB） ────────────────────────────────────


class TestTaskStatusChoices:
    """測試 TaskStatus 枚舉值。"""

    def test_has_all_expected_values(self):
        expected = {"pending", "running", "success", "failed", "retrying", "cancelled"}
        actual = {choice.value for choice in TaskStatus}
        assert actual == expected

    def test_labels(self):
        assert TaskStatus.PENDING.label == "等待中"
        assert TaskStatus.RUNNING.label == "執行中"
        assert TaskStatus.SUCCESS.label == "成功"
        assert TaskStatus.FAILED.label == "失敗"
        assert TaskStatus.RETRYING.label == "重試中"
        assert TaskStatus.CANCELLED.label == "已取消"


class TestTaskTypeChoices:
    """測試 TaskType 枚舉值。"""

    def test_has_all_expected_values(self):
        expected = {"command", "sync", "analysis"}
        actual = {choice.value for choice in TaskType}
        assert actual == expected

    def test_labels(self):
        assert TaskType.COMMAND.label == "一次性指令"
        assert TaskType.SYNC.label == "同步任務"
        assert TaskType.ANALYSIS.label == "分析/AI 長任務"


# ── BaseTask 核心邏輯測試（使用 mock，不需 DB） ─────────────────


class TestBaseTaskUpdateProgress:
    """測試 BaseTask.update_progress 的 percent 上限為 99。"""

    def _make_task_with_mock_request(self, task_id="fake-task-id"):
        """建立一個帶有 mock request 的 BaseTask 實例。"""
        from core._task_queue.base_task import BaseTask

        task = BaseTask()
        mock_request = MagicMock()
        mock_request.id = task_id
        # Celery 的 request 屬性透過 request_stack 取得，需要 mock 整個 property
        with patch.object(
            type(task), "request", new_callable=lambda: property(lambda self: mock_request)
        ):
            pass
        task._default_request = mock_request
        # 直接 patch request property
        type(task).request = property(lambda self: mock_request)
        return task

    @patch("core._task_queue.base_task.TaskProgress")
    def test_update_progress_caps_at_99(self, mock_model):
        """傳入 percent=100 時應被限制為 99。"""
        task = self._make_task_with_mock_request()

        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs

        task.update_progress(100, "完成中")

        mock_model.objects.filter.assert_called_once_with(celery_task_id="fake-task-id")
        mock_qs.update.assert_called_once_with(progress=99, message="完成中")

    @patch("core._task_queue.base_task.TaskProgress")
    def test_update_progress_normal_value(self, mock_model):
        """傳入 percent=50 時應維持原值。"""
        task = self._make_task_with_mock_request()

        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs

        task.update_progress(50, "處理中")

        mock_qs.update.assert_called_once_with(progress=50, message="處理中")

    @patch("core._task_queue.base_task.TaskProgress")
    def test_update_progress_zero(self, mock_model):
        """傳入 percent=0 時應維持 0。"""
        task = self._make_task_with_mock_request()

        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs

        task.update_progress(0)

        mock_qs.update.assert_called_once_with(progress=0, message="")


class TestBaseTaskCall:
    """測試 BaseTask.__call__ 的進度紀錄行為。"""

    @patch("core._task_queue.base_task.clear_context")
    @patch("core._task_queue.base_task.set_context")
    @patch("core._task_queue.base_task.publish_event")
    @patch("core._task_queue.base_task.TaskProgress")
    def test_call_reuses_existing_progress_for_retry(
        self,
        mock_progress_model,
        _mock_publish_event,
        _mock_set_context,
        _mock_clear_context,
    ):
        """重試同一個 Celery task id 時不應重複 create 進度列。"""
        from core._task_queue.base_task import BaseTask

        class SuccessfulTask(BaseTask):
            name = "test.success"

            def run(self):
                return {"ok": True}

        task = SuccessfulTask()
        mock_request = MagicMock()
        mock_request.id = "retry-task-id"
        mock_request.retries = 1
        mock_request.get.side_effect = lambda key, default=None: {
            "request_id": "request-1",
            "user_id": "user-1",
        }.get(key, default)
        type(task).request = property(lambda self: mock_request)
        progress = MagicMock()
        mock_progress_model.objects.update_or_create.return_value = (progress, False)

        result = task()

        assert result == {"ok": True}
        mock_progress_model.objects.update_or_create.assert_called_once()
        assert not mock_progress_model.objects.create.called
        assert progress.status == TaskStatus.SUCCESS
