#!/usr/bin/env python3
"""
hipstercheck - Dataset Collection for Code Review Model

This module collects and preprocesses code review datasets from multiple sources:
1. Hugging Face CodeReviewer dataset
2. GitHub PRs (optional, requires API token)
3. Local code review pairs

Output: Clean (code, review) pairs for fine-tuning.
"""

import os
import json
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime

try:
    from datasets import load_dataset

    HF_AVAILABLE = True
except ImportError:
    HF_AVAILABLE = False
    print(
        "Warning: 'datasets' library not installed. Install with: pip install datasets"
    )


class CodeReviewDatasetCollector:
    """Collect and preprocess code review datasets."""

    def __init__(self, output_dir: str = "dataset"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def collect_codereviewer_hf(self, split: str = "train") -> List[Dict]:
        """
        Load CodeReviewer dataset from Hugging Face.

        Dataset: CodeXGLUE/CodeReviewer
        Contains: (code, review) pairs with severity labels

        Returns:
            List of dicts with 'code', 'review', 'severity', 'category'
        """
        if not HF_AVAILABLE:
            raise ImportError("Install datasets: pip install datasets")

        print(f"Loading CodeReviewer dataset (split={split})...")
        dataset = load_dataset("CodeXGLUE/CodeReviewer", split=split)

        samples = []
        for item in dataset:
            # Map dataset fields to our format
            sample = {
                "code": item.get("code", ""),
                "review": item.get("review", ""),
                "severity": item.get("severity", "unknown"),
                "category": item.get("category", "general"),
                "source": "CodeXGLUE/CodeReviewer",
                "collected_at": datetime.utcnow().isoformat(),
            }
            samples.append(sample)

        print(f"Loaded {len(samples)} samples from CodeReviewer")
        return samples

    def collect_github_prs(
        self, token: Optional[str] = None, repos: List[str] = None, max_prs: int = 1000
    ) -> List[Dict]:
        """
        Scrape GitHub PRs with review comments.
        Requires: PyGithub and GitHub token.

        Args:
            token: GitHub personal access token
            repos: List of repos in 'owner/repo' format
            max_prs: Maximum number of PRs to fetch

        Returns:
            List of (code, review) pairs
        """
        from github import Github

        if token is None:
            token = os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("GitHub token required. Set GITHUB_TOKEN env var.")

        g = Github(token)
        samples = []

        if repos is None:
            # Default to popular Python/ML repos
            repos = [
                "python/cpython",
                "pytorch/pytorch",
                "tensorflow/tensorflow",
                "scikit-learn/scikit-learn",
                "ros2/ros2",
            ]

        print(f"Fetching PRs from {len(repos)} repos...")
        for repo_name in repos:
            try:
                repo = g.get_repo(repo_name)
                pulls = repo.get_pulls(state="closed", sort="updated", direction="desc")

                count = 0
                for pr in pulls:
                    if count >= max_prs // len(repos):
                        break

                    # Get PR files and review comments
                    files = pr.get_files()
                    comments = pr.get_review_comments()

                    for comment in comments:
                        # Extract code snippet around the comment
                        if comment.path and comment.diff_hunk:
                            sample = {
                                "code": self._extract_code_from_diff(comment.diff_hunk),
                                "review": comment.body,
                                "severity": self._classify_severity(comment.body),
                                "category": self._classify_category(comment.body),
                                "repo": repo_name,
                                "pr_number": pr.number,
                                "source": "GitHub PRs",
                                "collected_at": datetime.utcnow().isoformat(),
                            }
                            samples.append(sample)

                    count += 1

                print(f"  - {repo_name}: {count} PRs processed")

            except Exception as e:
                print(f"  - Error fetching {repo_name}: {e}")
                continue

        print(f"Collected {len(samples)} review samples from GitHub")
        return samples

    def _extract_code_from_diff(self, diff_hunk: str) -> str:
        """Extract the code lines from a diff hunk."""
        lines = []
        for line in diff_hunk.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                lines.append(line[1:])  # Remove the '+' prefix
        return "\n".join(lines).strip()

    def _classify_severity(self, comment_body: str) -> str:
        """Simple heuristic to classify severity."""
        body_lower = comment_body.lower()
        if any(
            word in body_lower
            for word in ["critical", "security", "bug", "error", "crash"]
        ):
            return "high"
        elif any(
            word in body_lower
            for word in ["performance", "optimization", "slow", "memory"]
        ):
            return "medium"
        else:
            return "low"

    def _classify_category(self, comment_body: str) -> str:
        """Classify review category."""
        body_lower = comment_body.lower()
        if any(word in body_lower for word in ["pep8", "style", "format", "indent"]):
            return "style"
        elif any(word in body_lower for word in ["bug", "error", "fix", "issue"]):
            return "bug"
        elif any(
            word in body_lower for word in ["performance", "optimization", "efficiency"]
        ):
            return "optimization"
        else:
            return "best_practice"

    def save_dataset(self, samples: List[Dict], filename: str = "code_reviews.jsonl"):
        """Save samples to JSONL file."""
        output_path = os.path.join(self.output_dir, filename)

        with open(output_path, "w") as f:
            for sample in samples:
                f.write(json.dumps(sample) + "\n")

        print(f"Saved {len(samples)} samples to {output_path}")
        return output_path

    def create_splits(
        self, samples: List[Dict], train_ratio: float = 0.8, val_ratio: float = 0.1
    ) -> Dict[str, List[Dict]]:
        """Split dataset into train/val/test."""
        import random

        random.shuffle(samples)

        n = len(samples)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))

        splits = {
            "train": samples[:train_end],
            "val": samples[train_end:val_end],
            "test": samples[val_end:],
        }

        for split_name, split_data in splits.items():
            output_file = os.path.join(self.output_dir, f"split_{split_name}.jsonl")
            with open(output_file, "w") as f:
                for sample in split_data:
                    f.write(json.dumps(sample) + "\n")
            print(f"  {split_name}: {len(split_data)} samples")

        return splits

    def generate_stats(self, samples: List[Dict]) -> Dict:
        """Generate dataset statistics."""
        if not samples:
            return {}

        stats = {
            "total_samples": len(samples),
            "sources": {},
            "severity_dist": {},
            "category_dist": {},
            "avg_code_length": sum(len(s.get("code", "")) for s in samples)
            / len(samples),
            "avg_review_length": sum(len(s.get("review", "")) for s in samples)
            / len(samples),
        }

        for sample in samples:
            source = sample.get("source", "unknown")
            stats["sources"][source] = stats["sources"].get(source, 0) + 1

            severity = sample.get("severity", "unknown")
            stats["severity_dist"][severity] = (
                stats["severity_dist"].get(severity, 0) + 1
            )

            category = sample.get("category", "unknown")
            stats["category_dist"][category] = (
                stats["category_dist"].get(category, 0) + 1
            )

        return stats


def main():
    """Main collection pipeline."""
    collector = CodeReviewDatasetCollector()

    all_samples = []

    # 1. Collect CodeReviewer from Hugging Face
    try:
        hf_samples = collector.collect_codereviewer_hf(split="train")
        all_samples.extend(hf_samples)
    except Exception as e:
        print(f"Failed to load CodeReviewer dataset: {e}")

    # 2. Optionally collect GitHub PRs (requires token)
    github_token = os.getenv("GITHUB_TOKEN")
    if github_token:
        try:
            gh_samples = collector.collect_github_prs(
                token=github_token,
                max_prs=500,  # Adjust as needed
            )
            all_samples.extend(gh_samples)
        except Exception as e:
            print(f"Failed to collect GitHub PRs: {e}")
    else:
        print("Skipping GitHub PR collection (GITHUB_TOKEN not set)")

    # Save complete dataset
    if all_samples:
        output_file = collector.save_dataset(all_samples)

        # Create splits
        splits = collector.create_splits(all_samples)

        # Generate and save stats
        stats = collector.generate_stats(all_samples)
        stats_file = os.path.join(collector.output_dir, "stats.json")
        with open(stats_file, "w") as f:
            json.dump(stats, f, indent=2)
        print(f"\nDataset Statistics:")
        print(json.dumps(stats, indent=2))

        print(f"\n✓ Dataset collection complete!")
        print(f"  Total samples: {stats['total_samples']}")
        print(f"  Output: {output_file}")
        print(f"  Splits: train/val/test created")
    else:
        print("No samples collected. Check data sources.")


if __name__ == "__main__":
    main()
