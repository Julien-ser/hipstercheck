"""
Unit tests for repo_scanner module
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from repo_scanner import RepoScanner, SUPPORTED_EXTENSIONS, EXCLUDED_DIRS


class TestRepoScannerInitialization:
    """Tests for RepoScanner initialization."""

    def test_init_with_token(self):
        """Test initialization with GitHub token."""
        scanner = RepoScanner("test_token")
        assert scanner.github is not None
        assert scanner.cache_ttl.total_seconds() == 24 * 3600

    def test_init_with_custom_cache_ttl(self):
        """Test initialization with custom cache TTL."""
        scanner = RepoScanner("test_token", cache_ttl_hours=12)
        assert scanner.cache_ttl.total_seconds() == 12 * 3600

    def test_cache_initialized_empty(self):
        """Test that cache is empty on init."""
        scanner = RepoScanner("test_token")
        assert scanner._cache == {}


class TestCacheOperations:
    """Tests for caching functionality."""

    def test_generate_cache_key(self):
        """Test cache key generation."""
        scanner = RepoScanner("test_token")
        key1 = scanner._generate_cache_key("owner/repo", "main")
        key2 = scanner._generate_cache_key("owner/repo", "develop")
        key3 = scanner._generate_cache_key("other/repo", "main")

        assert key1 != key2  # Different branches
        assert key1 != key3  # Different repos
        assert key1 == scanner._generate_cache_key(
            "owner/repo", "main"
        )  # Deterministic

    def test_cache_store_and_retrieve(self):
        """Test storing and retrieving from cache."""
        scanner = RepoScanner("test_token")
        test_data = {"repo_name": "test/repo", "file_tree": []}

        scanner.cache_scan("test/repo", test_data, "main")
        cached = scanner.get_cached_scan("test/repo", "main")

        assert cached == test_data

    def test_cache_expiration(self):
        """Test that expired cache returns None."""
        from datetime import datetime, timedelta

        scanner = RepoScanner("test_token", cache_ttl_hours=0.001)  # Very short TTL

        test_data = {"repo_name": "test/repo", "file_tree": []}
        scanner.cache_scan("test/repo", test_data)

        # Manually expire cache by setting old timestamp on the correct cache key
        cache_key = scanner._generate_cache_key("test/repo")
        old_time = datetime.now() - scanner.cache_ttl - timedelta(seconds=1)
        scanner._cache[cache_key] = {"timestamp": old_time, "data": test_data}
        result = scanner.get_cached_scan("test/repo")
        assert result is None

    def test_cache_not_expired(self):
        """Test that non-expired cache returns data."""
        scanner = RepoScanner("test_token", cache_ttl_hours=1)
        test_data = {"file_tree": []}
        scanner.cache_scan("test/repo", test_data)

        result = scanner.get_cached_scan("test/repo")
        assert result == test_data


class TestFileTreeExtraction:
    """Tests for file tree extraction."""

    def test_extract_file_tree_basic(self):
        """Test basic file tree extraction."""
        scanner = RepoScanner("test_token")

        # Create temporary directory with test files
        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            (root / "file1.py").write_text("print('hello')")
            (root / "file2.py").write_text("def foo(): pass")
            (root / "README.md").write_text("# README")
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("import os")
            (root / "tests").mkdir()
            (root / "tests" / "test.py").write_text("def test(): pass")

            files = scanner._extract_file_tree(temp_dir, "test/repo")

            # Should include all files (supported and unsupported)
            paths = [f["path"] for f in files]
            assert "file1.py" in paths
            assert "file2.py" in paths
            assert "src/main.py" in paths
            assert "tests/test.py" in paths
            assert "README.md" in paths  # Included but marked as unsupported
            # Check that README.md is marked as not supported
            readme_file = next(f for f in files if f["path"] == "README.md")
            assert readme_file["is_supported"] == False

        finally:
            shutil.rmtree(temp_dir)

    def test_extract_file_tree_excludes_dirs(self):
        """Test that excluded directories are skipped."""
        scanner = RepoScanner("test_token")

        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            (root / ".git" / "config").parent.mkdir(parents=True)
            (root / ".git" / "config").write_text("git config")
            (root / "__pycache__" / "file.pyc").parent.mkdir(parents=True)
            (root / "__pycache__" / "file.pyc").write_text("bytecode")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "pkg").mkdir()
            (root / "node_modules" / "pkg" / "index.js").write_text("js")
            (root / "good.py").write_text("# good")

            files = scanner._extract_file_tree(temp_dir, "test/repo")
            paths = [f["path"] for f in files]

            assert "good.py" in paths
            assert not any(".git" in p for p in paths)
            assert not any("__pycache__" in p for p in paths)
            assert not any("node_modules" in p for p in paths)

        finally:
            shutil.rmtree(temp_dir)

    def test_extract_file_tree_metadata(self):
        """Test that file metadata is correctly extracted."""
        scanner = RepoScanner("test_token")

        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            test_file = root / "test.py"
            test_file.write_text("# test content")

            files = scanner._extract_file_tree(temp_dir, "test/repo")
            f = files[0]

            assert f["name"] == "test.py"
            assert f["extension"] == ".py"
            assert f["language"] == "Python"
            assert f["is_supported"] == True
            assert f["path"] == "test.py"
            assert f["size"] > 0

        finally:
            shutil.rmtree(temp_dir)

    def test_extract_file_tree_unsupported_extensions(self):
        """Test that unsupported extensions are marked correctly."""
        scanner = RepoScanner("test_token")

        temp_dir = tempfile.mkdtemp()
        try:
            root = Path(temp_dir)
            (root / "file.txt").write_text("text")
            (root / "file.md").write_text("markdown")
            (root / "file.json").write_text("{}")
            (root / "file.xml").write_text("<xml/>")

            files = scanner._extract_file_tree(temp_dir, "test/repo")

            for f in files:
                assert f["is_supported"] == False
                assert f["language"] is None

        finally:
            shutil.rmtree(temp_dir)


class TestFilterSupportedFiles:
    """Tests for file filtering."""

    def test_filter_supported_files(self):
        """Test filtering for supported files."""
        scanner = RepoScanner("test_token")

        files = [
            {"path": "a.py", "extension": ".py", "is_supported": True},
            {"path": "b.js", "extension": ".js", "is_supported": False},
            {"path": "c.ipynb", "extension": ".ipynb", "is_supported": True},
            {"path": "d.yaml", "extension": ".yaml", "is_supported": True},
        ]

        filtered = scanner.filter_supported_files(files)
        assert len(filtered) == 3
        assert all(f["is_supported"] for f in filtered)

    def test_filter_supported_files_with_extensions(self):
        """Test filtering with specific extensions."""
        scanner = RepoScanner("test_token")

        files = [
            {"path": "a.py", "extension": ".py", "is_supported": True},
            {"path": "b.js", "extension": ".js", "is_supported": False},
            {"path": "c.ipynb", "extension": ".ipynb", "is_supported": True},
            {"path": "d.yaml", "extension": ".yaml", "is_supported": True},
        ]

        filtered = scanner.filter_supported_files(files, extensions=[".py"])
        assert len(filtered) == 1
        assert filtered[0]["path"] == "a.py"


class TestRepoSummary:
    """Tests for repository summary generation."""

    def test_get_repo_summary(self):
        """Test summary generation."""
        scanner = RepoScanner("test_token")

        scan_result = {
            "repo_name": "test/repo",
            "file_tree": [
                {
                    "path": "a.py",
                    "extension": ".py",
                    "is_supported": True,
                    "language": "Python",
                },
                {
                    "path": "b.py",
                    "extension": ".py",
                    "is_supported": True,
                    "language": "Python",
                },
                {
                    "path": "c.ipynb",
                    "extension": ".ipynb",
                    "is_supported": True,
                    "language": "Jupyter Notebook",
                },
                {
                    "path": "d.txt",
                    "extension": ".txt",
                    "is_supported": False,
                    "language": None,
                },
            ],
            "scanned_at": "2024-01-01T00:00:00",
        }

        summary = scanner.get_repo_summary(scan_result)

        assert summary["total_files"] == 4
        assert summary["supported_files"] == 3
        assert summary["coverage_pct"] == 75.0
        assert "Python" in summary["by_language"]
        assert summary["by_language"]["Python"] == 2
        assert "Jupyter Notebook" in summary["by_language"]
        assert summary["repo_name"] == "test/repo"


class TestSupportedExtensions:
    """Tests for supported file types."""

    def test_supported_extensions_include_all_required(self):
        """Verify all required extensions are supported."""
        required = [".py", ".launch", ".msg", ".ipynb", ".yaml", ".yml"]
        for ext in required:
            assert ext in SUPPORTED_EXTENSIONS, f"Missing extension: {ext}"

    def test_language_mapping(self):
        """Test that each extension has a language label."""
        for ext, lang in SUPPORTED_EXTENSIONS.items():
            assert isinstance(ext, str)
            assert isinstance(lang, str)
            assert len(lang) > 0


class TestExcludedDirs:
    """Tests for excluded directories."""

    def test_excluded_dirs_common_patterns(self):
        """Test common patterns are excluded."""
        expected = [".git", "__pycache__", "node_modules", "venv", ".venv"]
        for dirname in expected:
            assert dirname in EXCLUDED_DIRS, f"Missing excluded dir: {dirname}"


class TestIntegration:
    """Integration tests with mocked GitHub."""

    @patch("repo_scanner.Github")
    def test_scan_repository_flow(self, mock_github_class):
        """Test complete repository scanning flow."""
        # Mock GitHub objects
        mock_repo = Mock()
        mock_repo.clone_url = "https://github.com/owner/repo.git"
        mock_repo.private = False
        mock_repo.default_branch = "main"
        mock_repo.description = "Test repo"
        mock_repo.language = "Python"
        mock_repo.stargazers_count = 10

        mock_github = Mock()
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github

        scanner = RepoScanner("test_token")

        # Mock git.Repo.clone_from and shutil.rmtree
        with (
            patch("repo_scanner.git.Repo.clone_from") as mock_clone,
            patch("repo_scanner.shutil.rmtree"),
        ):
            # Create temp directory with files
            temp_dir = tempfile.mkdtemp()
            try:
                root = Path(temp_dir)
                (root / "main.py").write_text("print('hello')")
                (root / "test.py").write_text("def test(): pass")

                # Mock clone to use our temp dir
                def clone_side_effect(url, to_path, **kwargs):
                    # Copy our test files to the clone location
                    shutil.copytree(temp_dir, to_path, dirs_exist_ok=True)

                mock_clone.side_effect = clone_side_effect

                result = scanner.scan_repository("owner/repo")

                assert result["repo_name"] == "owner/repo"
                assert result["total_files"] >= 2
                assert result["supported_files"] >= 2
                assert "file_tree" in result

            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def test_scan_repository_uses_cache(self):
        """Test that cache is used on subsequent scans."""
        scanner = RepoScanner("test_token")

        # First scan (mocked)
        cached_data = {"repo_name": "test/repo", "file_tree": []}
        scanner.cache_scan("test/repo", cached_data)

        # Should return from cache
        result = scanner.get_cached_scan("test/repo")
        assert result == cached_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
