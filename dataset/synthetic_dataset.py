#!/usr/bin/env python3
"""
Generate synthetic code review dataset for training.
Creates Python code examples with intentional issues and corresponding reviews.
"""

import json
import random
from pathlib import Path
from typing import List, Dict


class SyntheticDatasetGenerator:
    """Generate synthetic code review examples."""

    def __init__(self, output_dir: str = "dataset"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_examples(self, num_examples: int = 1000) -> List[Dict]:
        """Generate a variety of code review examples."""
        templates = [
            self._undefined_variable,
            self._string_concat,
            self._missing_docstring,
            self._division_by_zero,
            self._mutable_default,
            self._unused_variable,
            self._missing_type_hint,
            self._inefficient_list_lookup,
            self._bare_except,
            self._hardcoded_secret,
        ]

        examples = []
        for i in range(num_examples):
            template_func = random.choice(templates)
            example = template_func()
            example["id"] = i
            examples.append(example)

        return examples

    def _undefined_variable(self) -> Dict:
        """Bug: using undefined variable."""
        code = """def process_data(items):
    for item in items:
        if item > 0:
            result.append(item)
    return result"""
        review = {
            "severity": "high",
            "line_number": 3,
            "category": "bug",
            "suggestion": "Initialize 'result = []' before the loop",
            "explanation": "Using an undefined variable will raise NameError at runtime. Initialize result as an empty list before the loop.",
            "code_example": "def process_data(items):\n    result = []\n    for item in items:\n        if item > 0:\n            result.append(item)\n    return result",
        }
        return {"code": code, "review": review, "language": "python"}

    def _string_concat(self) -> Dict:
        """Optimization: inefficient string concatenation."""
        code = """output = ""
for i in range(10000):
    output = output + str(i)"""
        review = {
            "severity": "medium",
            "line_number": 2,
            "category": "optimization",
            "suggestion": "Use list comprehension with ''.join() instead",
            "explanation": "String concatenation in a loop creates intermediate strings, O(n²) complexity. ''.join() is O(n) and much faster for large iterations.",
            "code_example": "output = ''.join(str(i) for i in range(10000))",
        }
        return {"code": code, "review": review, "language": "python"}

    def _missing_docstring(self) -> Dict:
        """Style: missing docstring."""
        code = """def calculate_avg(numbers):
    return sum(numbers) / len(numbers)"""
        review = {
            "severity": "low",
            "line_number": 1,
            "category": "style",
            "suggestion": "Add a docstring describing function purpose, parameters, and return value",
            "explanation": "Docstrings help other developers understand code without reading implementation. Use Google or NumPy style.",
            "code_example": 'def calculate_avg(numbers):\n    """Calculate arithmetic mean of a list.\n\n    Args:\n        numbers: List of numeric values\n\n    Returns:\n        Average as float\n    """\n    return sum(numbers) / len(numbers)',
        }
        return {"code": code, "review": review, "language": "python"}

    def _division_by_zero(self) -> Dict:
        """Bug: potential division by zero."""
        code = """def safe_divide(a, b):
    return a / b"""
        review = {
            "severity": "high",
            "line_number": 2,
            "category": "bug",
            "suggestion": "Add check: if b == 0: return 0 or raise ValueError",
            "explanation": "Division by zero raises ZeroDivisionError. Validate divisor before operation or use try/except.",
            "code_example": 'def safe_divide(a, b):\n    if b == 0:\n        raise ValueError("Cannot divide by zero")\n    return a / b',
        }
        return {"code": code, "review": review, "language": "python"}

    def _mutable_default(self) -> Dict:
        """Bug: mutable default argument."""
        code = """def add_item(item, items=[]):
    items.append(item)
    return items"""
        review = {
            "severity": "high",
            "line_number": 1,
            "category": "bug",
            "suggestion": "Use None as default and initialize inside function: items=None",
            "explanation": "Mutable default arguments are shared across calls, causing unexpected behavior. Use None and initialize inside function.",
            "code_example": "def add_item(item, items=None):\n    if items is None:\n        items = []\n    items.append(item)\n    return items",
        }
        return {"code": code, "review": review, "language": "python"}

    def _unused_variable(self) -> Dict:
        """Style: unused variable."""
        code = """def compute(x, y):
    temp = x + y
    return x * y"""
        review = {
            "severity": "low",
            "line_number": 2,
            "category": "style",
            "suggestion": "Remove unused variable 'temp' or use it if intended",
            "explanation": "Unused variables waste memory and indicate incomplete refactoring or bugs. Remove them or prefix with underscore if intentionally unused.",
            "code_example": "def compute(x, y):\n    return x * y",
        }
        return {"code": code, "review": review, "language": "python"}

    def _missing_type_hint(self) -> Dict:
        """Style: missing type hints in function signature."""
        code = """def process(data):
    return [x * 2 for x in data if x > 0]"""
        review = {
            "severity": "low",
            "line_number": 1,
            "category": "style",
            "suggestion": "Add type hints: def process(data: List[int]) -> List[int]",
            "explanation": "Type hints improve code readability, enable static analysis, and help IDEs provide better autocomplete. Essential for larger codebases.",
            "code_example": "from typing import List\n\ndef process(data: List[int]) -> List[int]:\n    return [x * 2 for x in data if x > 0]",
        }
        return {"code": code, "review": review, "language": "python"}

    def _inefficient_list_lookup(self) -> Dict:
        """Optimization: O(n) list lookup instead of O(1) set."""
        code = """def has_duplicate(items):
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i] == items[j]:
                return True
    return False"""
        review = {
            "severity": "medium",
            "line_number": 2,
            "category": "optimization",
            "suggestion": "Use a set for O(1) lookups: seen = set(); for x in items: if x in seen: return True",
            "explanation": "Current approach is O(n²) worst case. Using a set reduces complexity to O(n) with O(n) extra memory.",
            "code_example": "def has_duplicate(items):\n    seen = set()\n    for x in items:\n        if x in seen:\n            return True\n        seen.add(x)\n    return False",
        }
        return {"code": code, "review": review, "language": "python"}

    def _bare_except(self) -> Dict:
        """Style: bare except clause."""
        code = """try:
    data = json.loads(json_str)
except:
    return None"""
        review = {
            "severity": "medium",
            "line_number": 3,
            "category": "style",
            "suggestion": "Specify exception type: except json.JSONDecodeError:",
            "explanation": "Bare except clauses catch all exceptions including KeyboardInterrupt and SystemExit, making debugging harder and masking serious errors.",
            "code_example": "import json\n\ntry:\n    data = json.loads(json_str)\nexcept json.JSONDecodeError:\n    return None",
        }
        return {"code": code, "review": review, "language": "python"}

    def _hardcoded_secret(self) -> Dict:
        """Security: hardcoded API key."""
        code = """def connect_to_api():
    api_key = "sk-1234567890abcdef"
    headers = {"Authorization": f"Bearer {api_key}"}
    return requests.get(url, headers=headers)"""
        review = {
            "severity": "high",
            "line_number": 2,
            "category": "security",
            "suggestion": "Load API key from environment variable: os.getenv('API_KEY')",
            "explanation": "Hardcoded secrets in source code are a major security risk. Use environment variables or secret management services.",
            "code_example": 'import os\nimport requests\n\ndef connect_to_api():\n    api_key = os.getenv(\'API_KEY\')\n    if not api_key:\n        raise ValueError("API_KEY environment variable not set")\n    headers = {"Authorization": f"Bearer {api_key}"}\n    return requests.get(url, headers=headers)',
        }
        return {"code": code, "review": review, "language": "python"}

    def create_splits(
        self, examples: List[Dict], train_ratio: float = 0.8, val_ratio: float = 0.1
    ) -> Dict[str, List[Dict]]:
        """Split dataset into train/val/test."""
        random.shuffle(examples)

        n = len(examples)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))

        splits = {
            "train": examples[:train_end],
            "val": examples[train_end:val_end],
            "test": examples[val_end:],
        }

        for split_name, split_data in splits.items():
            output_file = self.output_dir / f"split_{split_name}.jsonl"
            with open(output_file, "w") as f:
                for sample in split_data:
                    f.write(json.dumps(sample) + "\n")
            print(f"  {split_name}: {len(split_data)} samples -> {output_file}")

        return splits

    def generate_stats(self, examples: List[Dict]) -> Dict:
        """Generate dataset statistics."""
        if not examples:
            return {}

        stats = {
            "total_samples": len(examples),
            "severity_dist": {},
            "category_dist": {},
            "avg_code_length": sum(len(ex.get("code", "")) for ex in examples)
            / len(examples),
            "avg_review_length": sum(
                len(json.dumps(ex.get("review", {}))) for ex in examples
            )
            / len(examples),
        }

        for ex in examples:
            review = ex.get("review", {})
            severity = review.get("severity", "unknown")
            stats["severity_dist"][severity] = (
                stats["severity_dist"].get(severity, 0) + 1
            )

            category = review.get("category", "unknown")
            stats["category_dist"][category] = (
                stats["category_dist"].get(category, 0) + 1
            )

        return stats


def main():
    """Generate and save synthetic dataset."""
    generator = SyntheticDatasetGenerator()

    print("Generating synthetic code review dataset...")
    examples = generator.generate_examples(num_examples=500)

    print("\nDataset Statistics:")
    stats = generator.generate_stats(examples)
    print(json.dumps(stats, indent=2))

    print("\nCreating splits...")
    splits = generator.create_splits(examples)

    stats_file = generator.output_dir / "synthetic_stats.json"
    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2)

    print(f"\n✓ Synthetic dataset generation complete!")
    print(f"  Total samples: {stats['total_samples']}")
    print(f"  Splits saved to dataset/")


if __name__ == "__main__":
    main()
