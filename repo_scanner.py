"""
Repo Scanner Module for hipstercheck

Provides functionality to scan GitHub repositories, extract file trees,
and filter files by supported types for code analysis.
"""

import os
import tempfile
import shutil
import time
from pathlib import Path
from typing import List, Dict, Set, Optional
from datetime import datetime, timedelta
import hashlib

from github import Github
from github.Repository import Repository
from github.GithubException import RateLimitExceededException, UnknownObjectException
import git
import redis


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

        # Initialize Redis cache if configured, otherwise use in-memory
        self.redis_url = os.getenv(
            "REDIS_URL", os.getenv("REDIS", "redis://localhost:6379")
        )
        self.use_redis = False
        self._cache: Dict[str, Dict] = {}  # Fallback in-memory cache

        try:
            self.redis_client = redis.from_url(
                self.redis_url, socket_timeout=5, socket_connect_timeout=5
            )
            # Test connection
            self.redis_client.ping()
            self.use_redis = True
            print("✅ Redis cache connected")
        except Exception as e:
            print(f"⚠️ Redis not available, using in-memory cache: {e}")
            self.redis_client = None

    def _generate_cache_key(self, repo_full_name: str, branch: str = None) -> str:
        """Generate a unique cache key for a repository."""
        key_str = f"{repo_full_name}:{branch or 'default'}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get_from_redis(self, key: str) -> Optional[Dict]:
        """Retrieve data from Redis."""
        if not self.use_redis or not self.redis_client:
            return None
        try:
            data = self.redis_client.get(f"hipstercheck:{key}")
            if data:
                import pickle

                return pickle.loads(data)
        except Exception as e:
            print(f"Redis get error: {e}")
        return None

    def set_to_redis(self, key: str, value: Dict, ttl_seconds: int):
        """Store data in Redis with TTL."""
        if not self.use_redis or not self.redis_client:
            return
        try:
            import pickle

            serialized = pickle.dumps(value)
            self.redis_client.setex(f"hipstercheck:{key}", ttl_seconds, serialized)
        except Exception as e:
            print(f"Redis set error: {e}")

    def get_cached_scan(
        self, repo_full_name: str, branch: str = None
    ) -> Optional[Dict]:
        """Retrieve cached scan results if available and not expired."""
        cache_key = self._generate_cache_key(repo_full_name, branch)

        # Try Redis first
        if self.use_redis:
            cached = self.get_from_redis(cache_key)
            if cached:
                return cached["data"] if "data" in cached else cached

        # Fallback to in-memory cache
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            if datetime.now() - cached["timestamp"] < self.cache_ttl:
                return cached["data"]
        return None

    def cache_scan(self, repo_full_name: str, scan_data: Dict, branch: str = None):
        """Cache scan results."""
        cache_key = self._generate_cache_key(repo_full_name, branch)
        data_to_store = {"timestamp": datetime.now(), "data": scan_data}

        # Store in Redis if available
        if self.use_redis:
            self.set_to_redis(
                cache_key, data_to_store, int(self.cache_ttl.total_seconds())
            )

        # Also store in memory as fallback
        self._cache[cache_key] = data_to_store

    def invalidate_cache(self, repo_full_name: str, branch: str = None):
        """Invalidate cached scan results for a repository."""
        cache_key = self._generate_cache_key(repo_full_name, branch)

        # Remove from Redis if available
        if self.use_redis and self.redis_client:
            try:
                self.redis_client.delete(f"hipstercheck:{cache_key}")
            except Exception as e:
                print(f"Redis delete error: {e}")

        # Remove from memory cache
        if cache_key in self._cache:
            del self._cache[cache_key]

    def get_cache_stats(self) -> Dict:
        """Get scan cache statistics."""
        memory_count = len(self._cache)

        redis_count = 0
        if self.use_redis and self.redis_client:
            try:
                keys = self.redis_client.keys("hipstercheck:*")
                redis_count = len(keys)
            except Exception as e:
                print(f"Redis keys error: {e}")

        total = memory_count + redis_count if self.use_redis else memory_count

        return {
            "memory_cache_size": memory_count,
            "redis_cache_size": redis_count if self.use_redis else 0,
            "backend": "redis+memory" if self.use_redis else "memory",
            "total_cached": total,
        }

    def check_rate_limit(self) -> Dict:
        """Check current GitHub API rate limit status."""
        try:
            rate_limit = self.github.get_rate_limit()
            return {
                "limit": rate_limit.core.limit,
                "remaining": rate_limit.core.remaining,
                "reset_time": rate_limit.core.reset.isoformat()
                if rate_limit.core.reset
                else None,
                "reset_epoch": rate_limit.core.reset.timestamp()
                if rate_limit.core.reset
                else None,
            }
        except Exception as e:
            return {"error": str(e), "limit": 0, "remaining": 0}

    def wait_for_rate_limit(self, buffer: int = 10):
        """Wait if rate limit is nearly exhausted."""
        rate_info = self.check_rate_limit()
        if "error" not in rate_info:
            remaining = rate_info["remaining"]
            try:
                remaining_int = int(remaining)
            except (TypeError, ValueError):
                remaining_int = float(
                    "inf"
                )  # If we can't parse, assume plenty remaining
            if remaining_int <= buffer:
                reset_time = rate_info.get("reset_epoch", time.time() + 3600)
                wait_seconds = max(1, reset_time - time.time() + 5)  # Add 5s buffer
                if wait_seconds > 0:
                    print(
                        f"⚠️ Rate limit low ({remaining} remaining). Waiting {wait_seconds:.0f}s..."
                    )
                    time.sleep(wait_seconds)

    def scan_repository(
        self, repo_full_name: str, progress_callback=None, force: bool = False
    ) -> Dict:
        """
        Scan a repository and extract file tree with metadata.

        Args:
            repo_full_name: Repository name (e.g., 'owner/repo')
            progress_callback: Optional callback(local_path, current, total) for progress
            force: If True, bypass cache and force fresh scan

        Returns:
            Dictionary with repository info and file tree
        """
        # Check cache first (unless forcing)
        if not force:
            cached = self.get_cached_scan(repo_full_name)
            if cached:
                return cached

        # Check rate limit before proceeding
        self.wait_for_rate_limit(buffer=int(os.getenv("RATE_LIMIT_BUFFER", "10")))

        # Get repository object
        try:
            repo = self.github.get_repo(repo_full_name)
        except RateLimitExceededException:
            raise Exception("GitHub API rate limit exceeded. Please try again later.")
        except UnknownObjectException:
            raise Exception(f"Repository '{repo_full_name}' not found or inaccessible.")

        # Create temporary directory for cloning
        temp_dir = tempfile.mkdtemp(prefix=f"hipstercheck_{repo.name}_")

        try:
            # Clone repository
            clone_url = repo.clone_url
            if repo.private:
                # For private repos, construct authenticated URL using token
                auth_token = self.github._Github__requester._Requester__authorizationHeader.replace(
                    "Bearer ", ""
                )
                clone_url = clone_url.replace(
                    "https://",
                    f"https://{auth_token}@",
                )

            # Clone without progress to avoid type issues
            git.Repo.clone_from(clone_url, temp_dir, depth=1)

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
