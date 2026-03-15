"""
Repo Scanner Module for hipstercheck

Provides functionality to scan GitHub repositories, extract file trees,
and filter files by supported types for code analysis.
"""

import os
import tempfile
import shutil
from pathlib import Path
from typing import List, Dict, Set, Optional
from datetime import datetime, timedelta
import hashlib

from github import Github
from github.Repository import Repository
import git


# Supported file extensions for analysis
SUPPORTED_EXTENSIONS = {
    ".py": "Python",
    ".launch": "ROS2 Launch",
    ".msg": "ROS2 Message",
    ".ipynb": "Jupyter Notebook",
    ".yaml": "YAML Config",
    ".yml": "YAML Config",
}

# Excluded directories (common in ML/ROS2 projects)
EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".pytest_cache",
    "coverage",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".vscode",
    ".idea",
    ".ipynb_checkpoints",
    "logs",
    "output",
    "models",
    "data",
}


class RepoScanner:
    """Scans GitHub repositories and extracts file trees for analysis."""

    def __init__(self, github_token: str, cache_ttl_hours: int = 24):
        """
        Initialize RepoScanner.

        Args:
            github_token: GitHub OAuth token for API access
            cache_ttl_hours: Cache time-to-live in hours
        """
        self.github = Github(github_token)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._cache: Dict[str, Dict] = {}

    def _generate_cache_key(self, repo_full_name: str, branch: str = None) -> str:
        """Generate a unique cache key for a repository."""
        key_str = f"{repo_full_name}:{branch or 'default'}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get_cached_scan(
        self, repo_full_name: str, branch: str = None
    ) -> Optional[Dict]:
        """Retrieve cached scan results if available and not expired."""
        cache_key = self._generate_cache_key(repo_full_name, branch)
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if datetime.now() - cached["timestamp"] < self.cache_ttl:
                return cached["data"]
        return None

    def cache_scan(self, repo_full_name: str, scan_data: Dict, branch: str = None):
        """Cache scan results."""
        cache_key = self._generate_cache_key(repo_full_name, branch)
        self._cache[cache_key] = {"timestamp": datetime.now(), "data": scan_data}

    def scan_repository(self, repo_full_name: str, progress_callback=None) -> Dict:
        """
        Scan a repository and extract file tree with metadata.

        Args:
            repo_full_name: Repository name (e.g., 'owner/repo')
            progress_callback: Optional callback(local_path, current, total) for progress

        Returns:
            Dictionary with repository info and file tree
        """
        # Check cache first
        cached = self.get_cached_scan(repo_full_name)
        if cached:
            return cached

        # Get repository object
        repo = self.github.get_repo(repo_full_name)

        # Create temporary directory for cloning
        temp_dir = tempfile.mkdtemp(prefix=f"hipstercheck_{repo.name}_")

        try:
            # Clone repository
            clone_url = repo.clone_url
            if repo.private:
                # For private repos, use token auth
                auth_url = clone_url.replace(
                    "https://",
                    f"https://{self.github._Github__requester._Requester__authorizationHeader}@",
                )
                clone_url = auth_url

            git.Repo.clone_from(
                clone_url, temp_dir, depth=1, progress=git.RemoteProgress()
            )

            # Walk file tree
            file_tree = self._extract_file_tree(
                temp_dir, repo_full_name, progress_callback
            )

            # Prepare result
            result = {
                "repo_name": repo_full_name,
                "clone_url": repo.clone_url,
                "default_branch": repo.default_branch,
                "description": repo.description,
                "language": repo.language,
                "stars": repo.stargazers_count,
                "private": repo.private,
                "file_tree": file_tree,
                "total_files": len(file_tree),
                "supported_files": sum(1 for f in file_tree if f["is_supported"]),
                "scanned_at": datetime.now().isoformat(),
            }

            # Cache the result
            self.cache_scan(repo_full_name, result)

            return result

        finally:
            # Cleanup temporary directory
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def _extract_file_tree(
        self, root_path: str, repo_full_name: str, progress_callback=None
    ) -> List[Dict]:
        """
        Extract file tree from local repository clone.

        Args:
            root_path: Path to the cloned repository
            repo_full_name: Repository full name for relative paths
            progress_callback: Optional callback for progress updates

        Returns:
            List of file dictionaries with metadata
        """
        files = []
        root = Path(root_path)

        # Get all files, excluding certain directories
        all_files = [p for p in root.rglob("*") if p.is_file()]
        total_files = len(all_files)

        for idx, file_path in enumerate(all_files):
            # Skip excluded directories
            if any(excluded in file_path.parts for excluded in EXCLUDED_DIRS):
                continue

            rel_path = str(file_path.relative_to(root))

            # Get file extension
            ext = file_path.suffix.lower()
            is_supported = ext in SUPPORTED_EXTENSIONS

            # Get file size
            try:
                size = file_path.stat().st_size
            except:
                size = 0

            files.append(
                {
                    "path": rel_path,
                    "name": file_path.name,
                    "extension": ext,
                    "language": SUPPORTED_EXTENSIONS.get(ext, "Unknown")
                    if is_supported
                    else None,
                    "size": size,
                    "is_supported": is_supported,
                }
            )

            # Report progress
            if progress_callback:
                progress_callback(repo_full_name, idx + 1, total_files)

        return files

    def filter_supported_files(
        self, file_tree: List[Dict], extensions: List[str] = None
    ) -> List[Dict]:
        """
        Filter file tree to only include supported file types.

        Args:
            file_tree: List of file dictionaries
            extensions: Optional list of extensions to filter by (defaults to all supported)

        Returns:
            Filtered list of file dictionaries
        """
        if extensions is None:
            return [f for f in file_tree if f["is_supported"]]
        return [f for f in file_tree if f["extension"] in extensions]

    def get_repo_summary(self, scan_result: Dict) -> Dict:
        """
        Generate summary statistics from scan results.

        Args:
            scan_result: Result from scan_repository()

        Returns:
            Dictionary with summary statistics
        """
        file_tree = scan_result["file_tree"]
        supported_files = self.filter_supported_files(file_tree)

        # Count by language
        by_language = {}
        for f in supported_files:
            lang = f["language"]
            by_language[lang] = by_language.get(lang, 0) + 1

        return {
            "total_files": len(file_tree),
            "supported_files": len(supported_files),
            "coverage_pct": (len(supported_files) / len(file_tree) * 100)
            if file_tree
            else 0,
            "by_language": by_language,
            "repo_name": scan_result["repo_name"],
            "scanned_at": scan_result["scanned_at"],
        }
