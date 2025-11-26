# Dify Workflow API Executor

Dify Workflow APIをバッチ実行するためのPython製CLIツール。CSVファイルを入力として受け取り、各行をDify Workflowに投げて、結果をJSONL形式で出力します。

## 背景

DifyのWorkflowバッチ処理機能に個人的に以下のような課題があったため、自前で API 実行してうまくハンドリングする本ツールを作成した。

- エラー発生時のリトライ制御が不十分
- 処理件数が増えると動作が不安定になることがある
- エラーハンドリングやログの詳細な制御が難しい

## 主要機能

- CSVファイルからのバッチ処理
- Workflow API実行
- 実行結果のJSONL形式での出力
- 自動リトライ
- 失敗したIDの記録とリトライ実行

## クイックスタート

### インストール

```bash
# リポジトリをクローン
git clone <repository-url>
cd dify-workflow-api-executor

# 依存パッケージをインストール
uv sync

# 環境変数を設定
cp .env.example .env
# .envファイルを編集してAPIキーとWorkflow IDを設定
```

### 環境変数設定

`.env` ファイルに以下の設定を記述:

```env
# 必須設定
DIFY_API_KEY=your-api-key-here
DIFY_WORKFLOW_ID=your-workflow-id-here

# オプション設定
DIFY_API_BASE_URL=https://api.dify.ai/v1
MAX_RETRIES=3
INITIAL_RETRY_DELAY=1
MAX_RETRY_DELAY=60
TIMEOUT=300
```

### 基本的な使い方

```bash
# CSVファイルを入力としてバッチ実行
uv run dify_workflow_executor.py --input data.csv --output results.jsonl

# 各リクエスト間に待機時間を設定（秒単位）
uv run dify_workflow_executor.py --input data.csv --output results.jsonl --wait 2

# 失敗したIDのみをリトライ実行
uv run dify_workflow_executor.py --input data.csv --output results.jsonl --retry

# 環境変数が正しく設定されているか確認
uv run dify_workflow_executor.py --validate
```

## コマンドライン引数

| 引数 | 短縮形 | 必須/オプション | デフォルト値 | 説明 |
|------|--------|----------------|--------------|------|
| `--input` | `-i` | 必須 | - | 入力CSVファイルのパス |
| `--output` | `-o` | 必須 | - | 出力JSONLファイルのパス |
| `--retry` | - | オプション | False | 失敗IDのみをリトライ実行 |
| `--wait` | `-w` | オプション | 0 | 各リクエスト間の待機時間（秒） |
| `--validate` | - | オプション | False | 設定の検証のみ実行 |

## CSVフォーマット

### 必須要件

- UTF-8エンコーディング
- ヘッダー行が必須
- 1列目に一意の `id` カラムが必須

### サンプル

```csv
id,user_name,query,language
req001,Alice,What is AI?,English
req002,Bob,AIとは何ですか,Japanese
req003,Charlie,Explain machine learning,English
```

ヘッダー名（`id` 以外）がそのままワークフロー入力パラメータ名として使用されます。

## 出力フォーマット

JSONL（JSON Lines）形式で出力されます。UTF-8 BOM付きで保存されます。

### 成功時の出力例

```jsonl
{"id": "req001", "status": "success", "inputs": {"user_name": "Alice", "query": "What is AI?"}, "outputs": {"answer": "..."}, "workflow_run_id": "...", "executed_at": "2025-11-26T12:34:56Z", "retry_count": 0}
```

### 失敗時の処理

失敗したIDは `.retry` ファイルに記録されます（例: `results.jsonl.retry`）。

```
req002
req005
```

リトライ実行時は `--retry` オプションを使用します。

## 開発

### テストの実行

```bash
# 全てのテストを実行
uv run pytest

# カバレッジレポート付き
uv run pytest --cov=dify_workflow_executor --cov-report=html
```

### 依存パッケージ

```toml
[project]
requires-python = ">=3.13"
dependencies = [
    "dify-client>=0.1.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.1.0",
]
```
