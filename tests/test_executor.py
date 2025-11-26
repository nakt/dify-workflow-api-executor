"""
Tests for Dify Workflow API Executor
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# メインスクリプトをインポート
sys.path.insert(0, str(Path(__file__).parent.parent))
from dify_workflow_executor import (
    Config,
    CSVReader,
    JSONLWriter,
    RetryFileManager,
    DifyWorkflowExecutor,
    RetryManager,
    ProgressTracker,
    BatchProcessor,
)


# =============================================================================
# Config クラスのテスト
# =============================================================================


class TestConfig:
    """Config クラスのテスト"""

    def test_from_env_success(self, monkeypatch):
        """環境変数から正しく設定を読み込めること"""
        monkeypatch.setenv("DIFY_API_KEY", "test-api-key")
        monkeypatch.setenv("DIFY_WORKFLOW_ID", "test-workflow-id")
        monkeypatch.setenv("MAX_RETRIES", "5")

        config = Config.from_env()

        assert config.api_key == "test-api-key"
        assert config.workflow_id == "test-workflow-id"
        assert config.max_retries == 5
        assert config.api_base_url == "https://api.dify.ai/v1"

    def test_from_env_missing_api_key(self, monkeypatch):
        """APIキーが未設定の場合にエラーが発生すること"""
        monkeypatch.delenv("DIFY_API_KEY", raising=False)
        monkeypatch.setenv("DIFY_WORKFLOW_ID", "test-workflow-id")

        with pytest.raises(ValueError, match="DIFY_API_KEY is required"):
            Config.from_env()

    def test_from_env_missing_workflow_id(self, monkeypatch):
        """Workflow IDが未設定の場合にエラーが発生すること"""
        monkeypatch.setenv("DIFY_API_KEY", "test-api-key")
        monkeypatch.delenv("DIFY_WORKFLOW_ID", raising=False)

        with pytest.raises(ValueError, match="DIFY_WORKFLOW_ID is required"):
            Config.from_env()


# =============================================================================
# CSVReader クラスのテスト
# =============================================================================


class TestCSVReader:
    """CSVReader クラスのテスト"""

    def test_read_rows_success(self, tmp_path):
        """CSVファイルを正しく読み込めること"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "id,name,query\n" "req001,Alice,What is AI?\n" "req002,Bob,Explain ML\n",
            encoding="utf-8",
        )

        reader = CSVReader(str(csv_file))
        rows = list(reader.read_rows())

        assert len(rows) == 2
        assert rows[0]["id"] == "req001"
        assert rows[0]["inputs"]["name"] == "Alice"
        assert rows[0]["inputs"]["query"] == "What is AI?"
        assert "id" not in rows[0]["inputs"]

    def test_read_rows_with_filter(self, tmp_path):
        """IDフィルターが正しく動作すること"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "id,name,query\n"
            "req001,Alice,What is AI?\n"
            "req002,Bob,Explain ML\n"
            "req003,Charlie,Deep Learning\n",
            encoding="utf-8",
        )

        reader = CSVReader(str(csv_file))
        rows = list(reader.read_rows(filter_ids=["req001", "req003"]))

        assert len(rows) == 2
        assert rows[0]["id"] == "req001"
        assert rows[1]["id"] == "req003"

    def test_read_rows_missing_id_column(self, tmp_path):
        """idカラムがない場合にエラーが発生すること"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,query\n" "Alice,What is AI?\n", encoding="utf-8")

        reader = CSVReader(str(csv_file))
        with pytest.raises(ValueError, match="must have 'id' column"):
            list(reader.read_rows())

    def test_read_rows_file_not_found(self):
        """ファイルが存在しない場合にエラーが発生すること"""
        with pytest.raises(FileNotFoundError):
            CSVReader("nonexistent.csv")


# =============================================================================
# JSONLWriter クラスのテスト
# =============================================================================


class TestJSONLWriter:
    """JSONLWriter クラスのテスト"""

    def test_write_result(self, tmp_path):
        """結果を正しくJSONL形式で書き込めること"""
        output_file = tmp_path / "output.jsonl"

        with JSONLWriter(str(output_file)) as writer:
            writer.write_result(
                {
                    "id": "req001",
                    "status": "success",
                    "inputs": {"name": "Alice"},
                    "outputs": {"answer": "AI is..."},
                }
            )

        # ファイルの内容を確認
        with open(output_file, "r", encoding="utf-8-sig") as f:
            line = f.readline()
            result = json.loads(line)
            assert result["id"] == "req001"
            assert result["status"] == "success"

    def test_write_multiple_results(self, tmp_path):
        """複数の結果を書き込めること"""
        output_file = tmp_path / "output.jsonl"

        with JSONLWriter(str(output_file)) as writer:
            writer.write_result({"id": "req001", "status": "success"})
            writer.write_result({"id": "req002", "status": "success"})

        # ファイルの行数を確認
        with open(output_file, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
            assert len(lines) == 2


# =============================================================================
# RetryFileManager クラスのテスト
# =============================================================================


class TestRetryFileManager:
    """RetryFileManager クラスのテスト"""

    def test_add_and_load_failed_ids(self, tmp_path):
        """失敗IDを追加して読み込めること"""
        retry_file = tmp_path / "test.retry"
        manager = RetryFileManager(str(retry_file))

        manager.add_failed_id("req001")
        manager.add_failed_id("req002")

        failed_ids = manager.load_failed_ids()
        assert failed_ids == ["req001", "req002"]

    def test_remove_id(self, tmp_path):
        """IDを削除できること"""
        retry_file = tmp_path / "test.retry"
        manager = RetryFileManager(str(retry_file))

        manager.add_failed_id("req001")
        manager.add_failed_id("req002")
        manager.add_failed_id("req003")

        manager.remove_id("req002")

        failed_ids = manager.load_failed_ids()
        assert failed_ids == ["req001", "req003"]

    def test_clear(self, tmp_path):
        """ファイルを削除できること"""
        retry_file = tmp_path / "test.retry"
        manager = RetryFileManager(str(retry_file))

        manager.add_failed_id("req001")
        assert retry_file.exists()

        manager.clear()
        assert not retry_file.exists()

    def test_load_empty_file(self, tmp_path):
        """存在しないファイルから読み込んだ場合に空リストが返ること"""
        retry_file = tmp_path / "nonexistent.retry"
        manager = RetryFileManager(str(retry_file))

        failed_ids = manager.load_failed_ids()
        assert failed_ids == []


# =============================================================================
# RetryManager クラスのテスト
# =============================================================================


class TestRetryManager:
    """RetryManager クラスのテスト"""

    def test_should_retry_retryable_error(self):
        """リトライ可能なエラーの場合にTrueを返すこと"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.should_retry("RateLimitError", attempt=0) is True
        assert manager.should_retry("APIError", attempt=1) is True
        assert manager.should_retry("TimeoutError", attempt=2) is True

    def test_should_retry_non_retryable_error(self):
        """リトライ不可能なエラーの場合にFalseを返すこと"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.should_retry("AuthenticationError", attempt=0) is False
        assert manager.should_retry("ValidationError", attempt=1) is False

    def test_should_retry_max_attempts_exceeded(self):
        """最大リトライ回数を超えた場合にFalseを返すこと"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.should_retry("APIError", attempt=3) is False

    def test_get_delay_exponential_backoff(self):
        """エクスポネンシャルバックオフで遅延時間が増加すること"""
        manager = RetryManager(max_retries=5, initial_delay=1.0, max_delay=60.0)

        delay0 = manager.get_delay(0)
        delay1 = manager.get_delay(1)
        delay2 = manager.get_delay(2)

        # 指数関数的に増加するが、jitterがあるので厳密な比較はしない
        assert 1.0 <= delay0 <= 1.2
        assert 2.0 <= delay1 <= 2.2
        assert 4.0 <= delay2 <= 4.2

    def test_get_delay_max_cap(self):
        """最大遅延時間を超えないこと"""
        manager = RetryManager(max_retries=10, initial_delay=1.0, max_delay=10.0)

        delay = manager.get_delay(10)  # 1024秒になるはずだが
        assert delay <= 10.1  # max_delay + jitter

    def test_is_fatal_error(self):
        """致命的エラーを正しく判定すること"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.is_fatal_error("AuthenticationError") is True
        assert manager.is_fatal_error("ValidationError") is False
        assert manager.is_fatal_error("APIError") is False


# =============================================================================
# ProgressTracker クラスのテスト
# =============================================================================


class TestProgressTracker:
    """ProgressTracker クラスのテスト"""

    def test_update_success(self):
        """成功カウントが更新されること"""
        tracker = ProgressTracker(total_rows=10)

        tracker.update(success=True)
        assert tracker.success_count == 1
        assert tracker.failed_count == 0

    def test_update_failure(self):
        """失敗カウントが更新されること"""
        tracker = ProgressTracker(total_rows=10)

        tracker.update(success=False)
        assert tracker.success_count == 0
        assert tracker.failed_count == 1

    def test_format_time(self):
        """時間フォーマットが正しいこと"""
        assert ProgressTracker._format_time(30) == "30s"
        assert ProgressTracker._format_time(90) == "1m 30s"
        assert ProgressTracker._format_time(3661) == "1h 1m"


# =============================================================================
# DifyWorkflowExecutor クラスのテスト
# =============================================================================


class TestDifyWorkflowExecutor:
    """DifyWorkflowExecutor クラスのテスト"""

    def test_execute_success(self, monkeypatch):
        """ワークフローが正常に実行されること"""
        config = Config(api_key="test-key", workflow_id="test-workflow")

        # CompletionClientのモック
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json = Mock(
            return_value={"answer": "AI is...", "message_id": "msg_123"}
        )

        with patch("dify_workflow_executor.CompletionClient") as mock_client_class:
            mock_client = Mock()
            mock_client.create_completion_message = Mock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            executor = DifyWorkflowExecutor(config)
            result = executor.execute({"query": "What is AI?"})

            assert result["success"] is True
            assert result["workflow_run_id"] == "msg_123"
            assert result["outputs"]["answer"] == "AI is..."

    def test_execute_failure(self, monkeypatch):
        """ワークフロー実行が失敗した場合にエラー情報を返すこと"""
        config = Config(api_key="test-key", workflow_id="test-workflow")

        with patch("dify_workflow_executor.CompletionClient") as mock_client_class:
            mock_client = Mock()
            mock_client.create_completion_message = Mock(
                side_effect=Exception("API Error")
            )
            mock_client_class.return_value = mock_client

            executor = DifyWorkflowExecutor(config)
            result = executor.execute({"query": "What is AI?"})

            assert result["success"] is False
            assert result["error_type"] == "Exception"
            assert "API Error" in result["error"]


# =============================================================================
# 統合テスト
# =============================================================================


class TestBatchProcessorIntegration:
    """BatchProcessor の統合テスト"""

    @pytest.fixture
    def mock_config(self):
        """テスト用のConfig"""
        return Config(
            api_key="test-key",
            workflow_id="test-workflow",
            max_retries=2,
            initial_retry_delay=0.01,
            max_retry_delay=0.1,
        )

    def test_process_all_success(self, tmp_path, mock_config):
        """全行が成功する場合のテスト"""
        # 入力CSV
        csv_file = tmp_path / "input.csv"
        csv_file.write_text(
            "id,query\n" "req001,What is AI?\n" "req002,Explain ML\n", encoding="utf-8"
        )

        # 出力JSONL
        output_file = tmp_path / "output.jsonl"

        # CompletionClientのモックを作成
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json = Mock(
            return_value={"answer": "Test answer", "message_id": "msg_123"}
        )

        with patch("dify_workflow_executor.CompletionClient") as mock_client_class:
            mock_client = Mock()
            mock_client.create_completion_message = Mock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            processor = BatchProcessor(mock_config)
            processor.process(
                csv_path=str(csv_file),
                output_path=str(output_file),
                retry_mode=False,
                wait_seconds=0,
            )

        # 結果を確認
        with open(output_file, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
            assert len(lines) == 2

            # 各行がJSONとしてパースできることを確認
            for line in lines:
                result = json.loads(line)
                assert result["status"] == "success"
                assert "id" in result
                assert result["outputs"]["answer"] == "Test answer"

        # .retryファイルが存在しないことを確認
        retry_file = Path(f"{output_file}.retry")
        assert not retry_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
