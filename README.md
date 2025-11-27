# Dify Workflow API Executor

A Python CLI tool for batch execution of Dify Workflow API. It accepts CSV files as input, processes each row through Dify Workflow, and outputs results in JSONL format.

## Background

This tool was created to address personal challenges with Dify's built-in Workflow batch processing feature:

- Insufficient retry control when errors occur
- Unstable behavior when processing large volumes
- Difficult to control detailed error handling and logging

## Key Features

- Batch processing from CSV files
- Workflow API execution
- Output results in JSONL format
- Automatic retry with exponential backoff
- Failed ID tracking and retry execution

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd dify-workflow-api-executor

# Install dependencies
uv sync

# Set up environment variables
cp .env.example .env
# Edit .env file to configure API key and Workflow ID
```

### Environment Variables

Configure the following in your `.env` file:

```env
# Required settings
DIFY_API_KEY=your-api-key-here
DIFY_WORKFLOW_ID=your-workflow-id-here

# Optional settings
DIFY_API_BASE_URL=https://api.dify.ai/v1
MAX_RETRIES=3
INITIAL_RETRY_DELAY=1
MAX_RETRY_DELAY=60
TIMEOUT=300
```

### Basic Usage

```bash
# Batch execution with CSV input
uv run dify_workflow_executor.py --input data.csv --output results.jsonl

# Set wait time between requests (in seconds)
uv run dify_workflow_executor.py --input data.csv --output results.jsonl --wait 2

# Retry only failed IDs
uv run dify_workflow_executor.py --input data.csv --output results.jsonl --retry
```

## Command Line Arguments

| Argument | Short | Required/Optional | Default | Description |
|----------|-------|-------------------|---------|-------------|
| `--input` | `-i` | Required | - | Path to input CSV file |
| `--output` | `-o` | Required | - | Path to output JSONL file |
| `--retry` | - | Optional | False | Retry only failed IDs |
| `--wait` | `-w` | Optional | 0 | Wait time between requests (seconds) |

## CSV Format

### Requirements

- UTF-8 encoding
- Header row is required
- First column must be unique `id` column

### Example

```csv
id,user_name,query,language
req001,Alice,What is AI?,English
req002,Bob,AIとは何ですか,Japanese
req003,Charlie,Explain machine learning,English
```

Header names (including `id`) are used as workflow input parameter names.

## Output Format

Results are output in JSONL (JSON Lines) format with UTF-8 BOM encoding.

### Success Output Example

```jsonl
{"id": "req001", "status": "success", "inputs": {"id": "req001", "user_name": "Alice", "query": "What is AI?"}, "outputs": {"result": "..."}, "workflow_run_id": "...", "executed_at": "2025-11-26T12:34:56Z", "retry_count": 0}
```

### Failed ID Handling

Failed IDs are recorded in a `.retry` file (e.g., `results.jsonl.retry`):

```
req002
req005
```

Use the `--retry` option to retry failed IDs.

## Development

### Running Tests

To run tests, first install development dependencies:

```bash
# Install dev dependencies
uv sync --extra dev

# Run all tests
uv run pytest

# With coverage report
uv run pytest --cov=dify_workflow_executor --cov-report=html
```

**Note**: Some tests may need updates to reflect recent changes from Completion API to Workflow API migration.

### Dependencies

The project requires Python 3.13+ and the following dependencies:

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
