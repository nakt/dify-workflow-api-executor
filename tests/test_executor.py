"""
Tests for Dify Workflow API Executor
"""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Import main script
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
# Tests for Config class
# =============================================================================


class TestConfig:
    """Tests for Config class"""

    def test_from_env_success(self, monkeypatch):
        """Successfully load configuration from environment variables"""
        monkeypatch.setenv("DIFY_API_KEY", "test-api-key")
        monkeypatch.setenv("DIFY_WORKFLOW_ID", "test-workflow-id")
        monkeypatch.setenv("MAX_RETRIES", "5")

        config = Config.from_env()

        assert config.api_key == "test-api-key"
        assert config.workflow_id == "test-workflow-id"
        assert config.max_retries == 5
        assert config.api_base_url == "https://api.dify.ai/v1"

    def test_from_env_missing_api_key(self, monkeypatch, tmp_path):
        """Error occurs when API key is not set"""
        # Change current directory to avoid .env file interference
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DIFY_API_KEY", raising=False)
        monkeypatch.setenv("DIFY_WORKFLOW_ID", "test-workflow-id")

        with pytest.raises(ValueError, match="DIFY_API_KEY is required"):
            Config.from_env()

    def test_from_env_missing_workflow_id(self, monkeypatch, tmp_path):
        """Error occurs when Workflow ID is not set"""
        # Change current directory to avoid .env file interference
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DIFY_API_KEY", "test-api-key")
        monkeypatch.delenv("DIFY_WORKFLOW_ID", raising=False)

        with pytest.raises(ValueError, match="DIFY_WORKFLOW_ID is required"):
            Config.from_env()


# =============================================================================
# Tests for CSVReader class
# =============================================================================


class TestCSVReader:
    """Tests for CSVReader class"""

    def test_read_rows_success(self, tmp_path):
        """Successfully read CSV file"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text(
            "id,name,query\n" "req001,Alice,What is AI?\n" "req002,Bob,Explain ML\n",
            encoding="utf-8",
        )

        reader = CSVReader(str(csv_file))
        rows = list(reader.read_rows())

        assert len(rows) == 2
        assert rows[0]["id"] == "req001"
        assert rows[0]["inputs"]["id"] == "req001"
        assert rows[0]["inputs"]["name"] == "Alice"
        assert rows[0]["inputs"]["query"] == "What is AI?"

    def test_read_rows_with_filter(self, tmp_path):
        """ID filter works correctly"""
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
        """Error occurs when id column is missing"""
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,query\n" "Alice,What is AI?\n", encoding="utf-8")

        reader = CSVReader(str(csv_file))
        with pytest.raises(ValueError, match="must have 'id' column"):
            list(reader.read_rows())

    def test_read_rows_file_not_found(self):
        """Error occurs when file does not exist"""
        with pytest.raises(FileNotFoundError):
            CSVReader("nonexistent.csv")


# =============================================================================
# Tests for JSONLWriter class
# =============================================================================


class TestJSONLWriter:
    """Tests for JSONLWriter class"""

    def test_write_result(self, tmp_path):
        """Successfully write results in JSONL format"""
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

        # Verify file contents
        with open(output_file, "r", encoding="utf-8-sig") as f:
            line = f.readline()
            result = json.loads(line)
            assert result["id"] == "req001"
            assert result["status"] == "success"

    def test_write_multiple_results(self, tmp_path):
        """Successfully write multiple results"""
        output_file = tmp_path / "output.jsonl"

        with JSONLWriter(str(output_file)) as writer:
            writer.write_result({"id": "req001", "status": "success"})
            writer.write_result({"id": "req002", "status": "success"})

        # Verify number of lines in file
        with open(output_file, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
            assert len(lines) == 2


# =============================================================================
# Tests for RetryFileManager class
# =============================================================================


class TestRetryFileManager:
    """Tests for RetryFileManager class"""

    def test_add_and_load_failed_ids(self, tmp_path):
        """Successfully add and load failed IDs"""
        retry_file = tmp_path / "test.retry"
        manager = RetryFileManager(str(retry_file))

        manager.add_failed_id("req001")
        manager.add_failed_id("req002")

        failed_ids = manager.load_failed_ids()
        assert failed_ids == ["req001", "req002"]

    def test_remove_id(self, tmp_path):
        """Successfully remove ID"""
        retry_file = tmp_path / "test.retry"
        manager = RetryFileManager(str(retry_file))

        manager.add_failed_id("req001")
        manager.add_failed_id("req002")
        manager.add_failed_id("req003")

        manager.remove_id("req002")

        failed_ids = manager.load_failed_ids()
        assert failed_ids == ["req001", "req003"]

    def test_clear(self, tmp_path):
        """Successfully delete file"""
        retry_file = tmp_path / "test.retry"
        manager = RetryFileManager(str(retry_file))

        manager.add_failed_id("req001")
        assert retry_file.exists()

        manager.clear()
        assert not retry_file.exists()

    def test_load_empty_file(self, tmp_path):
        """Return empty list when loading from nonexistent file"""
        retry_file = tmp_path / "nonexistent.retry"
        manager = RetryFileManager(str(retry_file))

        failed_ids = manager.load_failed_ids()
        assert failed_ids == []


# =============================================================================
# Tests for RetryManager class
# =============================================================================


class TestRetryManager:
    """Tests for RetryManager class"""

    def test_should_retry_retryable_error(self):
        """Return True for retryable errors"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.should_retry("RateLimitError", attempt=0) is True
        assert manager.should_retry("APIError", attempt=1) is True
        assert manager.should_retry("TimeoutError", attempt=2) is True

    def test_should_retry_non_retryable_error(self):
        """Return False for non-retryable errors"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.should_retry("AuthenticationError", attempt=0) is False
        assert manager.should_retry("ValidationError", attempt=1) is False

    def test_should_retry_max_attempts_exceeded(self):
        """Return False when max retry attempts exceeded"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.should_retry("APIError", attempt=3) is False

    def test_get_delay_exponential_backoff(self):
        """Delay time increases with exponential backoff"""
        manager = RetryManager(max_retries=5, initial_delay=1.0, max_delay=60.0)

        delay0 = manager.get_delay(0)
        delay1 = manager.get_delay(1)
        delay2 = manager.get_delay(2)

        # Increases exponentially, but not strict comparison due to jitter
        assert 1.0 <= delay0 <= 1.2
        assert 2.0 <= delay1 <= 2.2
        assert 4.0 <= delay2 <= 4.2

    def test_get_delay_max_cap(self):
        """Does not exceed maximum delay time"""
        manager = RetryManager(max_retries=10, initial_delay=1.0, max_delay=10.0)

        delay = manager.get_delay(10)  # Would be 1024s but capped
        assert delay <= 10.1  # max_delay + jitter

    def test_is_fatal_error(self):
        """Correctly determine fatal errors"""
        manager = RetryManager(max_retries=3, initial_delay=1.0, max_delay=60.0)

        assert manager.is_fatal_error("AuthenticationError") is True
        assert manager.is_fatal_error("ValidationError") is False
        assert manager.is_fatal_error("APIError") is False


# =============================================================================
# Tests for ProgressTracker class
# =============================================================================


class TestProgressTracker:
    """Tests for ProgressTracker class"""

    def test_update_success(self):
        """Success count is updated"""
        tracker = ProgressTracker(total_rows=10)

        tracker.update(success=True)
        assert tracker.success_count == 1
        assert tracker.failed_count == 0

    def test_update_failure(self):
        """Failure count is updated"""
        tracker = ProgressTracker(total_rows=10)

        tracker.update(success=False)
        assert tracker.success_count == 0
        assert tracker.failed_count == 1

    def test_format_time(self):
        """Time format is correct"""
        assert ProgressTracker._format_time(30) == "30s"
        assert ProgressTracker._format_time(90) == "1m 30s"
        assert ProgressTracker._format_time(3661) == "1h 1m"


# =============================================================================
# Tests for DifyWorkflowExecutor class
# =============================================================================


class TestDifyWorkflowExecutor:
    """Tests for DifyWorkflowExecutor class"""

    def test_execute_success(self, monkeypatch):
        """Workflow executes successfully"""
        config = Config(api_key="test-key", workflow_id="test-workflow")

        # Mock WorkflowClient
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json = Mock(
            return_value={
                "workflow_run_id": "wf_123",
                "data": {"outputs": {"result": "AI is..."}}
            }
        )

        with patch("dify_workflow_executor.WorkflowClient") as mock_client_class:
            mock_client = Mock()
            mock_client.run_workflow = Mock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            executor = DifyWorkflowExecutor(config)
            result = executor.execute({"query": "What is AI?"})

            assert result["success"] is True
            assert result["workflow_run_id"] == "wf_123"
            assert result["outputs"]["outputs"]["result"] == "AI is..."

    def test_execute_failure(self, monkeypatch):
        """Return error information when workflow execution fails"""
        config = Config(api_key="test-key", workflow_id="test-workflow")

        with patch("dify_workflow_executor.WorkflowClient") as mock_client_class:
            mock_client = Mock()
            mock_client.run_workflow = Mock(
                side_effect=Exception("API Error")
            )
            mock_client_class.return_value = mock_client

            executor = DifyWorkflowExecutor(config)
            result = executor.execute({"query": "What is AI?"})

            assert result["success"] is False
            assert result["error_type"] == "Exception"
            assert "API Error" in result["error"]


# =============================================================================
# Integration tests
# =============================================================================


class TestBatchProcessorIntegration:
    """Integration tests for BatchProcessor"""

    @pytest.fixture
    def mock_config(self):
        """Config for testing"""
        return Config(
            api_key="test-key",
            workflow_id="test-workflow",
            max_retries=2,
            initial_retry_delay=0.01,
            max_retry_delay=0.1,
        )

    def test_process_all_success(self, tmp_path, mock_config):
        """Test when all rows succeed"""
        # Input CSV
        csv_file = tmp_path / "input.csv"
        csv_file.write_text(
            "id,query\n" "req001,What is AI?\n" "req002,Explain ML\n", encoding="utf-8"
        )

        # Output JSONL
        output_file = tmp_path / "output.jsonl"

        # Create mock for WorkflowClient
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json = Mock(
            return_value={
                "workflow_run_id": "wf_123",
                "data": {"outputs": {"result": "Test answer"}}
            }
        )

        with patch("dify_workflow_executor.WorkflowClient") as mock_client_class:
            mock_client = Mock()
            mock_client.run_workflow = Mock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            processor = BatchProcessor(mock_config)
            processor.process(
                csv_path=str(csv_file),
                output_path=str(output_file),
                retry_mode=False,
                wait_seconds=0,
            )

        # Verify results
        with open(output_file, "r", encoding="utf-8-sig") as f:
            lines = f.readlines()
            assert len(lines) == 2

            # Verify each line can be parsed as JSON
            for line in lines:
                result = json.loads(line)
                assert result["status"] == "success"
                assert "id" in result
                assert result["outputs"]["outputs"]["result"] == "Test answer"

        # Verify .retry file does not exist
        retry_file = Path(f"{output_file}.retry")
        assert not retry_file.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
