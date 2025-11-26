# Dify Workflow API Executor - 設計ドキュメント

## 概要

Dify Workflow APIをバッチ実行するためのPython製CLIツール。CSVファイルを入力として受け取り、各行をDify Workflowに投げて、結果をJSONL形式で出力します。

## 主要機能

- CSVファイルからのバッチ処理
- Dify公式SDK (dify-client) を使用したWorkflow API実行
- 実行結果のJSONL形式での出力
- エクスポネンシャルバックオフによる自動リトライ
- 失敗したIDの記録とリトライ実行
- プログレス表示
- 詳細なエラーハンドリング

## システム要件

- Python 3.13以上
- uv（パッケージマネージャー）
- Dify APIキーとWorkflow ID
- 依存パッケージ:
  - dify-client>=0.1.0
  - python-dotenv>=1.0.0

## インストール方法

```bash
# リポジトリをクローン
git clone <repository-url>
cd dify-workflow-api-executor

# uvを使って依存パッケージをインストール
uv sync

# 環境変数を設定
cp .env.example .env
# .envファイルを編集してAPIキーとWorkflow IDを設定
```

## 環境変数設定

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

### 環境変数の説明

| 変数名 | 必須/オプション | デフォルト値 | 説明 |
|--------|----------------|--------------|------|
| `DIFY_API_KEY` | 必須 | - | DifyのAPIキー |
| `DIFY_WORKFLOW_ID` | 必須 | - | 実行するWorkflowのID |
| `DIFY_API_BASE_URL` | オプション | `https://api.dify.ai/v1` | DifyのAPIベースURL |
| `MAX_RETRIES` | オプション | `3` | 最大リトライ回数 |
| `INITIAL_RETRY_DELAY` | オプション | `1` | 初回リトライ遅延秒数 |
| `MAX_RETRY_DELAY` | オプション | `60` | 最大リトライ遅延秒数 |
| `TIMEOUT` | オプション | `300` | APIタイムアウト秒数 |

## 使用方法

### 基本的な使い方

```bash
# CSVファイルを入力としてバッチ実行
uv run dify-workflow-executor.py --input data.csv --output results.jsonl

# 各リクエスト間に待機時間を設定（秒単位）
uv run dify-workflow-executor.py --input data.csv --output results.jsonl --wait 2
```

### 失敗したIDのリトライ

```bash
# .retryファイルに記録された失敗IDのみを再実行
uv run dify-workflow-executor.py --input data.csv --output results.jsonl --retry
```

### 設定の検証のみ

```bash
# 環境変数が正しく設定されているか確認
uv run dify-workflow-executor.py --validate
```

### コマンドライン引数

| 引数 | 短縮形 | 必須/オプション | デフォルト値 | 説明 |
|------|--------|----------------|--------------|------|
| `--input` | `-i` | 必須 | - | 入力CSVファイルのパス |
| `--output` | `-o` | 必須 | - | 出力JSONLファイルのパス |
| `--retry` | - | オプション | False | 失敗IDのみをリトライ実行 |
| `--wait` | `-w` | オプション | 0 | 各リクエスト間の待機時間（秒） |
| `--validate` | - | オプション | False | 設定の検証のみ実行 |

## CSVフォーマット仕様

### 必須要件

- UTF-8エンコーディング
- ヘッダー行が必須
- 1列目に一意のIDカラムが必須

### CSVの例

```csv
id,user_name,query,language
req001,Alice,What is AI?,English
req002,Bob,AIとは何ですか,Japanese
req003,Charlie,Explain machine learning,English
```

### カラムのマッピング

CSVのヘッダー名が、そのままDify Workflowの入力パラメータ名として使用されます。

例: 上記CSVの場合、Workflowには以下のように渡されます:

```json
{
  "user_name": "Alice",
  "query": "What is AI?",
  "language": "English"
}
```

※ `id` カラムは内部管理用に使用され、Workflowには渡されません

## JSONL出力フォーマット

### エンコーディング

UTF-8 with BOM（Excel対応）

### 出力スキーマ

成功した実行結果のみがJSONL形式で記録されます:

```jsonl
{"id": "req001", "status": "success", "inputs": {"user_name": "Alice", "query": "What is AI?", "language": "English"}, "outputs": {"answer": "Artificial Intelligence is..."}, "workflow_run_id": "wfr_abc123", "executed_at": "2025-11-26T12:34:56Z", "retry_count": 0}
{"id": "req003", "status": "success", "inputs": {"user_name": "Charlie", "query": "Explain machine learning", "language": "English"}, "outputs": {"answer": "Machine Learning is..."}, "workflow_run_id": "wfr_def456", "executed_at": "2025-11-26T12:35:10Z", "retry_count": 1}
```

### フィールドの説明

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `id` | string | CSVの1列目のID |
| `status` | string | 実行ステータス（常に `"success"`） |
| `inputs` | object | Workflowへの入力パラメータ |
| `outputs` | object | Workflowからの出力結果 |
| `workflow_run_id` | string | Difyの実行ID |
| `executed_at` | string | 実行日時（ISO8601形式） |
| `retry_count` | integer | リトライ回数（0から開始） |

## リトライ機能

### .retryファイル

失敗したIDは `<output_path>.retry` ファイルに記録されます。

例: `results.jsonl` を出力先に指定した場合、失敗IDは `results.jsonl.retry` に記録されます。

### .retryファイルの形式

UTF-8 with BOM、1行に1つのID:

```
req002
req005
req007
```

### リトライの流れ

1. 初回実行: `uv run dify-workflow-executor.py --input data.csv --output results.jsonl`
   - 成功したIDは `results.jsonl` に記録
   - 失敗したIDは `results.jsonl.retry` に記録

2. リトライ実行: `uv run dify-workflow-executor.py --input data.csv --output results.jsonl --retry`
   - `.retry` ファイルからIDリストを読込
   - CSVから該当IDの行のみを抽出して再実行
   - 成功したIDは `results.jsonl` に追記され、`.retry` から削除
   - 失敗したIDは `.retry` に残る

3. 再度リトライ可能（成功するまで繰り返し可能）

## エラーハンドリング

### エラータイプと処理

| エラータイプ | リトライ | 動作 | 説明 |
|-------------|---------|------|------|
| `AuthenticationError` | 不可 | バッチ処理を即座に中断 | APIキーが不正 |
| `ValidationError` | 不可 | 該当行をスキップ | 入力パラメータが不正 |
| `RateLimitError` | 可 | エクスポネンシャルバックオフでリトライ | レート制限超過 |
| `APIError` | 可 | エクスポネンシャルバックオフでリトライ | その他のAPIエラー |
| `TimeoutError` | 可 | エクスポネンシャルバックオフでリトライ | タイムアウト |
| `NetworkError` | 可 | エクスポネンシャルバックオフでリトライ | ネットワークエラー |

### エクスポネンシャルバックオフ

リトライ時の待機時間は以下の式で計算されます:

```
delay = min(INITIAL_RETRY_DELAY * (2 ** attempt) + jitter, MAX_RETRY_DELAY)
```

- `jitter`: 0〜0.1秒のランダムな揺らぎ（サンダリングハード問題の回避）
- 例: `INITIAL_RETRY_DELAY=1`, `MAX_RETRY_DELAY=60` の場合
  - 1回目: 1秒 + jitter
  - 2回目: 2秒 + jitter
  - 3回目: 4秒 + jitter
  - 4回目: 8秒 + jitter
  - ...
  - 最大60秒

## プログレス表示

### 実行中の表示

```
Progress: [=======>    ] 45/100 (45%) | Success: 40 | Failed: 5 | ETA: 2m 30s
```

### 完了時のサマリー

```
========================================
Batch Processing Complete
========================================
Total processed: 100
Successful: 95
Failed: 5
Total time: 5m 23s
========================================
```

## ログ

ログは以下の2箇所に出力されます:

1. コンソール（標準出力）
2. `dify-workflow-executor.log` ファイル

### ログレベル

- `INFO`: 処理の開始、進捗、完了
- `WARNING`: リトライ実行
- `ERROR`: 認証失敗、バッチ処理の中断

## トラブルシューティング

### 認証エラーが発生する

症状: `AuthenticationError` が発生し、バッチ処理が中断される

原因:
- `.env` ファイルの `DIFY_API_KEY` が不正
- APIキーの権限が不足

対処法:
1. `.env` ファイルを確認
2. DifyのダッシュボードでAPIキーを再確認
3. APIキーを再生成して設定

### すべての行が ValidationError になる

症状: すべての行がスキップされる

原因:
- CSVのヘッダー名とWorkflowの入力パラメータ名が一致しない
- Workflowが必要とするパラメータが不足

対処法:
1. Workflowの入力パラメータ名を確認
2. CSVのヘッダー名を修正
3. 必須パラメータがすべて含まれているか確認

### タイムアウトが頻発する

症状: `TimeoutError` が多発する

原因:
- Workflowの処理時間が長い
- ネットワークが遅い

対処法:
1. `.env` の `TIMEOUT` を増やす（例: `TIMEOUT=600`）
2. Workflowの処理を最適化
3. ネットワーク環境を確認

### .retryファイルが削除されない

症状: リトライ実行後も `.retry` ファイルにIDが残る

原因:
- リトライ後も失敗している
- エラーがリトライ不可能なタイプ（ValidationErrorなど）

対処法:
1. ログを確認してエラータイプを特定
2. ValidationErrorの場合、該当IDのCSV行を修正
3. 手動で `.retry` ファイルから該当IDを削除

## 制限事項

1. シングルスレッド実行: 並列処理には対応していません（順次処理のみ）
2. UTF-8のみ対応: Shift-JISなど他のエンコーディングには対応していません
3. 同期実行のみ: Dify Workflowのストリーミングモードには対応していません
4. IDカラム必須: CSVの1列目にIDカラムが必須です
5. 失敗履歴の非保存: 失敗した実行結果はJSONLに記録されません（IDのみ`.retry`ファイルに記録）

## アーキテクチャ

### コンポーネント構成

```
dify-workflow-executor.py
├── Config                  # 環境変数管理
├── CSVReader               # CSV入力処理
├── DifyWorkflowExecutor    # Dify API呼び出し
├── RetryManager            # リトライロジック
├── JSONLWriter             # JSONL出力
├── RetryFileManager        # .retryファイル管理
├── ProgressTracker         # プログレス表示
└── BatchProcessor          # バッチ処理統括
```

### データフロー

```
CSV入力
  ↓
IDカラム検証
  ↓
各行を順次処理
  ├─ Workflow実行成功 → JSONL出力
  └─ Workflow実行失敗 → .retryファイルに記録
        ↓
   リトライ実行（--retry オプション）
        ↓
   .retryファイルからID読込 → 該当行のみ再実行
```

## ファイル一覧

- `dify-workflow-executor.py` - メイン実装ファイル
- `pyproject.toml` - プロジェクト設定と依存パッケージ定義（uv管理）
- `uv.lock` - 依存パッケージのロックファイル（uv自動生成）
- `.env.example` - 環境変数サンプル
- `.env` - 環境変数設定（ユーザーが作成）
- `dify-workflow-executor.log` - 実行ログ（自動生成）
- `<output_path>` - JSONL出力ファイル（実行時に指定）
- `<output_path>.retry` - 失敗ID記録ファイル（自動生成）

## ライセンス

TBD
