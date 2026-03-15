# Dataset Directory

This directory contains code review datasets for fine-tuning the hipstercheck AI model.

## Contents

- `data_collector.py` - Main script for collecting and preprocessing code review data
- `code_reviews.jsonl` - Combined dataset in JSONL format (generated)
- `split_train.jsonl` - Training split
- `split_val.jsonl` - Validation split  
- `split_test.jsonl` - Test split
- `stats.json` - Dataset statistics (generated)

## Data Sources

### 1. CodeXGLUE/CodeReviewer (Hugging Face)
- **Description**: Public dataset of code reviews with severity labels
- **Format**: (code, review, severity, category)
- **License**: Open (check Hugging Face for details)

### 2. GitHub Pull Request Comments (Optional)
- **Description**: Real-world review comments from popular open-source repositories
- **Format**: (code snippet, review comment, severity, category, repo, pr_number)
- **Requirements**: GitHub token (`GITHUB_TOKEN` environment variable)
- **Repos**: Python, PyTorch, TensorFlow, scikit-learn, ROS2

## Usage

### Collect Dataset

```bash
# Install dependencies
pip install datasets pygithub

# For GitHub PR collection (optional)
export GITHUB_TOKEN="your_github_personal_access_token"

# Run collection
python dataset/data_collector.py
```

### Output Format

Each line in the JSONL files contains a JSON object:

```json
{
  "code": "def calculate_sum(a, b):\n    return a + b",
  "review": "Add type hints for better clarity: def calculate_sum(a: int, b: int) -> int:",
  "severity": "low",
  "category": "best_practice",
  "source": "CodeXGLUE/CodeReviewer",
  "collected_at": "2026-03-15T12:00:00.000000"
}
```

### Data Schema

| Field | Type | Description |
|-------|------|-------------|
| `code` | str | Code snippet (can be function, class, or method) |
| `review` | str | AI-generated or human review comment |
| `severity` | str | One of: `high`, `medium`, `low`, `unknown` |
| `category` | str | One of: `bug`, `style`, `optimization`, `best_practice`, `general` |
| `source` | str | Origin of the data point |
| `collected_at` | str | ISO 8601 timestamp of collection |

### Splits

- **Train** (80%): Used for model training
- **Validation** (10%): Used for hyperparameter tuning
- **Test** (10%): Used for final evaluation

## Notes

- Code snippets are extracted from diff hunks for PR data
- Severity categories are automatically classified using heuristics
- The dataset is continuously expandable with additional sources
- For production use, consider quality control: deduplication, filtering low-quality reviews, manual verification

## License

The dataset inherits licenses from its sources. Check individual source licenses before commercial use.