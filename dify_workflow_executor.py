#!/usr/bin/env python3
"""
Dify Workflow API Executor
CLI tool for batch execution of Dify Workflow API
"""

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from dotenv import load_dotenv
from dify_client import CompletionClient


# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("dify-workflow-executor.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# =============================================================================
# 1. Config クラス
# =============================================================================


@dataclass
class Config:
    """環境変数から設定を読み込むクラス"""

    api_key: str
    workflow_id: str
    api_base_url: str = "https://api.dify.ai/v1"
    max_retries: int = 3
    initial_retry_delay: float = 1.0
    max_retry_delay: float = 60.0
    timeout: int = 300

    @classmethod
    def from_env(cls) -> "Config":
        """環境変数から設定を読み込む"""
        load_dotenv()

        api_key = os.getenv("DIFY_API_KEY")
        workflow_id = os.getenv("DIFY_WORKFLOW_ID")

        if not api_key:
            raise ValueError("DIFY_API_KEY is required in .env file")
        if not workflow_id:
            raise ValueError("DIFY_WORKFLOW_ID is required in .env file")

        return cls(
            api_key=api_key,
            workflow_id=workflow_id,
            api_base_url=os.getenv("DIFY_API_BASE_URL", "https://api.dify.ai/v1"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            initial_retry_delay=float(os.getenv("INITIAL_RETRY_DELAY", "1.0")),
            max_retry_delay=float(os.getenv("MAX_RETRY_DELAY", "60.0")),
            timeout=int(os.getenv("TIMEOUT", "300")),
        )

    def validate(self) -> None:
        """設定の妥当性を検証"""
        logger.info("Validating configuration...")
        logger.info(f"  API Base URL: {self.api_base_url}")
        logger.info(f"  Workflow ID: {self.workflow_id}")
        logger.info(f"  Max Retries: {self.max_retries}")
        logger.info(f"  Timeout: {self.timeout}s")
        logger.info("Configuration is valid")


# =============================================================================
# 2. CSVReader クラス
# =============================================================================


class CSVReader:
    """CSV入力を処理するクラス"""

    def __init__(self, csv_path: str):
        self.csv_path = Path(csv_path)
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        self.headers: List[str] = []

    def read_rows(
        self, filter_ids: Optional[List[str]] = None
    ) -> Iterator[Dict[str, Any]]:
        """
        CSVを1行ずつ読み込み、辞書形式で返す

        Args:
            filter_ids: 指定されたIDのみを読み込む（リトライモード用）

        Yields:
            {
                "id": "unique_id",
                "inputs": {"column1": "value1", "column2": "value2", ...}
            }
        """
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.headers = list(reader.fieldnames or [])

            if not self.headers:
                raise ValueError("CSV file has no headers")

            if "id" not in self.headers:
                raise ValueError("CSV file must have 'id' column as the first column")

            for row in reader:
                row_id = row.get("id", "").strip()
                if not row_id:
                    logger.warning("Skipping row with empty ID")
                    continue

                # フィルターが指定されている場合、該当IDのみを処理
                if filter_ids is not None and row_id not in filter_ids:
                    continue

                # idカラムを除外して入力パラメータを作成
                inputs = {k: v for k, v in row.items() if k != "id"}

                yield {"id": row_id, "inputs": inputs}


# =============================================================================
# 3. JSONLWriter クラス
# =============================================================================


class JSONLWriter:
    """JSONL形式で結果を出力するクラス"""

    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
        self.file_handle: Optional[Any] = None

    def __enter__(self):
        # UTF-8 with BOMで開く
        self.file_handle = open(self.output_path, "a", encoding="utf-8-sig")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.file_handle:
            self.file_handle.close()

    def write_result(self, result: Dict[str, Any]) -> None:
        """
        実行結果を1行ずつJSONL形式で書き込み

        Args:
            result: {
                "id": str,
                "status": "success",
                "inputs": Dict[str, Any],
                "outputs": Dict[str, Any],
                "workflow_run_id": str,
                "executed_at": str,
                "retry_count": int
            }
        """
        if not self.file_handle:
            raise RuntimeError("JSONLWriter must be used within a context manager")

        json_line = json.dumps(result, ensure_ascii=False)
        self.file_handle.write(json_line + "\n")
        self.file_handle.flush()


# =============================================================================
# 4. RetryFileManager クラス
# =============================================================================


class RetryFileManager:
    """失敗したIDを.retryファイルで管理するクラス"""

    def __init__(self, retry_file_path: str):
        self.retry_file_path = Path(retry_file_path)

    def add_failed_id(self, row_id: str) -> None:
        """失敗IDを追記"""
        with open(self.retry_file_path, "a", encoding="utf-8-sig") as f:
            f.write(row_id + "\n")
            f.flush()

    def load_failed_ids(self) -> List[str]:
        """失敗IDリストを読込"""
        if not self.retry_file_path.exists():
            return []

        with open(self.retry_file_path, "r", encoding="utf-8-sig") as f:
            return [line.strip() for line in f if line.strip()]

    def remove_id(self, row_id: str) -> None:
        """指定されたIDを削除"""
        if not self.retry_file_path.exists():
            return

        # 既存のIDを読み込み
        failed_ids = self.load_failed_ids()

        # 指定されたIDを除外
        updated_ids = [id for id in failed_ids if id != row_id]

        # ファイルを上書き
        with open(self.retry_file_path, "w", encoding="utf-8-sig") as f:
            for id in updated_ids:
                f.write(id + "\n")

    def clear(self) -> None:
        """.retryファイルを削除"""
        if self.retry_file_path.exists():
            self.retry_file_path.unlink()


# =============================================================================
# 5. DifyWorkflowExecutor クラス
# =============================================================================


class DifyWorkflowExecutor:
    """Dify Workflow APIのラッパークラス"""

    def __init__(self, config: Config):
        self.config = config
        self.client = CompletionClient(config.api_key)

    def execute(
        self, inputs: Dict[str, Any], user: str = "batch-executor"
    ) -> Dict[str, Any]:
        """
        ワークフローを同期実行

        Returns:
            {
                "success": True/False,
                "workflow_run_id": str or None,
                "outputs": dict or None,
                "error": str or None,
                "error_type": str or None
            }
        """
        try:
            response = self.client.create_completion_message(
                inputs=inputs, response_mode="blocking", user=user
            )

            # レスポンスのステータスコードをチェック
            response.raise_for_status()

            # JSONレスポンスをパース
            result = response.json()

            # CompletionClientの場合、answerフィールドに結果が入る
            answer = result.get("answer", "")
            message_id = result.get("message_id", "")

            # 全体のレスポンスをoutputsとして保存
            outputs = {"answer": answer, "metadata": result.get("metadata", {})}

            return {
                "success": True,
                "workflow_run_id": message_id,
                "outputs": outputs,
                "error": None,
                "error_type": None,
            }

        except Exception as e:
            error_type = type(e).__name__
            error_message = str(e)

            logger.warning(f"Workflow execution failed: {error_type} - {error_message}")

            return {
                "success": False,
                "workflow_run_id": None,
                "outputs": None,
                "error": error_message,
                "error_type": error_type,
            }


# =============================================================================
# 6. RetryManager クラス
# =============================================================================


class RetryManager:
    """エクスポネンシャルバックオフによるリトライを管理するクラス"""

    # リトライ不可能なエラータイプ
    NON_RETRYABLE_ERRORS = {"AuthenticationError", "ValidationError"}

    def __init__(self, max_retries: int, initial_delay: float, max_delay: float):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay

    def should_retry(self, error_type: str, attempt: int) -> bool:
        """リトライすべきかを判定"""
        if error_type in self.NON_RETRYABLE_ERRORS:
            return False

        return attempt < self.max_retries

    def get_delay(self, attempt: int) -> float:
        """
        エクスポネンシャルバックオフで待機時間を計算

        Formula: min(initial_delay * (2 ** attempt) + jitter, max_delay)
        """
        delay = self.initial_delay * (2**attempt)
        jitter = random.uniform(
            0, 0.1
        )  # nosec B311 - jitter for retry backoff, not security-critical
        return min(delay + jitter, self.max_delay)

    def is_fatal_error(self, error_type: str) -> bool:
        """バッチ処理全体を中断すべきエラーかを判定"""
        return error_type == "AuthenticationError"


# =============================================================================
# 7. ProgressTracker クラス
# =============================================================================


class ProgressTracker:
    """実行進捗を表示するクラス"""

    def __init__(self, total_rows: int):
        self.total_rows = total_rows
        self.success_count = 0
        self.failed_count = 0
        self.start_time = time.time()

    def update(self, success: bool) -> None:
        """進捗を更新"""
        if success:
            self.success_count += 1
        else:
            self.failed_count += 1

        current = self.success_count + self.failed_count
        percentage = (current / self.total_rows * 100) if self.total_rows > 0 else 0

        # ETA計算
        elapsed = time.time() - self.start_time
        if current > 0:
            avg_time = elapsed / current
            remaining = self.total_rows - current
            eta_seconds = avg_time * remaining
            eta_str = self._format_time(eta_seconds)
        else:
            eta_str = "N/A"

        # プログレスバー
        bar_length = 20
        filled_length = (
            int(bar_length * current / self.total_rows) if self.total_rows > 0 else 0
        )
        bar = "=" * filled_length + ">" + " " * (bar_length - filled_length - 1)

        print(
            f"\rProgress: [{bar}] {current}/{self.total_rows} ({percentage:.1f}%) | "
            f"Success: {self.success_count} | Failed: {self.failed_count} | ETA: {eta_str}",
            end="",
            flush=True,
        )

    def display_summary(self) -> None:
        """最終結果サマリーを表示"""
        print()  # 改行
        total_time = time.time() - self.start_time
        total_processed = self.success_count + self.failed_count

        print("=" * 40)
        print("Batch Processing Complete")
        print("=" * 40)
        print(f"Total processed: {total_processed}")
        print(f"Successful: {self.success_count}")
        print(f"Failed: {self.failed_count}")
        print(f"Total time: {self._format_time(total_time)}")
        print("=" * 40)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """秒数を読みやすい形式に変換"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"


# =============================================================================
# 8. BatchProcessor クラス
# =============================================================================


class BatchProcessor:
    """バッチ処理全体を統括するクラス"""

    def __init__(self, config: Config):
        self.config = config
        self.executor = DifyWorkflowExecutor(config)
        self.retry_manager = RetryManager(
            config.max_retries, config.initial_retry_delay, config.max_retry_delay
        )

    def process(
        self,
        csv_path: str,
        output_path: str,
        retry_mode: bool = False,
        wait_seconds: float = 0,
    ) -> None:
        """
        CSVファイルをバッチ処理

        Args:
            csv_path: 入力CSVファイルパス
            output_path: 出力JSONLファイルパス
            retry_mode: Trueの場合、既存の.retryから失敗行のみを再実行
            wait_seconds: 各リクエスト間の待機時間（秒）
        """
        retry_file_path = f"{output_path}.retry"
        retry_manager = RetryFileManager(retry_file_path)

        # リトライモードの場合、失敗IDを読み込む
        filter_ids = None
        if retry_mode:
            filter_ids = retry_manager.load_failed_ids()
            if not filter_ids:
                logger.info("No failed IDs found in .retry file. Nothing to retry.")
                return
            logger.info(f"Retry mode: Processing {len(filter_ids)} failed IDs")

        # CSVリーダーを初期化
        csv_reader = CSVReader(csv_path)

        # 総行数を取得（プログレス表示用）
        rows_list = list(csv_reader.read_rows(filter_ids))
        total_rows = len(rows_list)

        if total_rows == 0:
            logger.info("No rows to process")
            return

        logger.info(f"Starting batch processing: {total_rows} rows")

        # プログレストラッカーを初期化
        progress = ProgressTracker(total_rows)

        # JSONLライターを開く
        with JSONLWriter(output_path) as writer:
            for i, row in enumerate(rows_list):
                row_id = row["id"]
                inputs = row["inputs"]

                logger.info(f"Processing row {i+1}/{total_rows}: ID={row_id}")

                # 1行を処理（リトライ含む）
                result = self._process_row(row_id, inputs, retry_count=0)

                if result["status"] == "success":
                    # 成功した結果をJSONLに書き込み
                    writer.write_result(result)
                    # .retryファイルから削除
                    retry_manager.remove_id(row_id)
                    progress.update(success=True)
                else:
                    # 失敗した場合、.retryファイルに記録
                    retry_manager.add_failed_id(row_id)
                    progress.update(success=False)

                    # 致命的なエラー（認証エラー）の場合、バッチ処理を中断
                    if self.retry_manager.is_fatal_error(result.get("error_type", "")):
                        logger.error(
                            f"Fatal error occurred: {result['error_type']}. Aborting batch process."
                        )
                        break

                # 最後の行以外は待機
                if i < total_rows - 1 and wait_seconds > 0:
                    time.sleep(wait_seconds)

        # サマリー表示
        progress.display_summary()

        # 残りの失敗IDを確認
        remaining_failures = retry_manager.load_failed_ids()
        if remaining_failures:
            logger.info(
                f"{len(remaining_failures)} IDs failed. Retry with --retry option."
            )
        else:
            logger.info("All rows processed successfully!")
            # .retryファイルを削除
            retry_manager.clear()

    def _process_row(
        self, row_id: str, inputs: Dict[str, Any], retry_count: int
    ) -> Dict[str, Any]:
        """
        1行を処理（リトライ含む）

        Returns:
            {
                "id": str,
                "status": "success",
                "inputs": Dict[str, Any],
                "outputs": Dict[str, Any],
                "workflow_run_id": str,
                "executed_at": str,
                "retry_count": int
            }
        """
        result = self.executor.execute(inputs)

        if result["success"]:
            return {
                "id": row_id,
                "status": "success",
                "inputs": inputs,
                "outputs": result["outputs"],
                "workflow_run_id": result["workflow_run_id"],
                "executed_at": datetime.utcnow().isoformat() + "Z",
                "retry_count": retry_count,
            }

        # 失敗した場合、リトライを検討
        error_type = result["error_type"]

        if self.retry_manager.should_retry(error_type, retry_count):
            # リトライ待機
            delay = self.retry_manager.get_delay(retry_count)
            logger.warning(
                f"Retrying row ID={row_id} after {delay:.1f}s (attempt {retry_count + 1}/{self.config.max_retries})"
            )
            time.sleep(delay)

            # 再帰的にリトライ
            return self._process_row(row_id, inputs, retry_count + 1)

        # リトライ不可能な場合、失敗として返す
        logger.error(
            f"Row ID={row_id} failed after {retry_count} retries: {error_type}"
        )
        return {
            "id": row_id,
            "status": "failed",
            "inputs": inputs,
            "outputs": None,
            "workflow_run_id": None,
            "error": result["error"],
            "error_type": error_type,
            "executed_at": datetime.utcnow().isoformat() + "Z",
            "retry_count": retry_count,
        }


# =============================================================================
# 9. CLI インターフェース
# =============================================================================


def main():
    """メイン関数"""
    parser = argparse.ArgumentParser(
        description="Dify Workflow Batch Executor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--input", "-i", help="Input CSV file path")
    parser.add_argument("--output", "-o", help="Output JSONL file path")
    parser.add_argument(
        "--retry", action="store_true", help="Retry failed IDs from .retry file"
    )
    parser.add_argument(
        "--wait",
        "-w",
        type=float,
        default=0,
        help="Wait time between requests in seconds (default: 0)",
    )
    parser.add_argument(
        "--validate", action="store_true", help="Validate configuration only"
    )

    args = parser.parse_args()

    try:
        # 設定を読み込み
        config = Config.from_env()

        # バリデーションのみの場合
        if args.validate:
            config.validate()
            return 0

        # 入力・出力パスのチェック
        if not args.input or not args.output:
            parser.error(
                "--input and --output are required (unless --validate is specified)"
            )

        # バッチ処理を実行
        processor = BatchProcessor(config)
        processor.process(
            csv_path=args.input,
            output_path=args.output,
            retry_mode=args.retry,
            wait_seconds=args.wait,
        )

        return 0

    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
        return 130

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
