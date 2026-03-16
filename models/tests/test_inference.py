"""Tests for the inference module."""

import pytest
import json
from pathlib import Path

# Import the module we're testing
# Note: This test file will be run in an environment with dependencies installed
try:
    from models.inference import CodeReviewModel, get_model

    DEPENDENCIES_AVAILABLE = True
except ImportError as e:
    DEPENDENCIES_AVAILABLE = False
    pytest.skip(f"Required dependencies not available: {e}", allow_module_level=True)


class TestCodeReviewModel:
    """Tests for CodeReviewModel class."""

    def test_init_with_base_model_only(self, tmp_path):
        """Test initialization with base model (no fine-tuned weights)."""
        model = CodeReviewModel(
            model_path=None, base_model_name="microsoft/phi-2", device="cpu"
        )
        assert model is not None
        assert model.device == "cpu"
        assert model.tokenizer is not None
        assert model.model is not None

    def test_create_prompt(self):
        """Test prompt generation."""
        model = CodeReviewModel(device="cpu")

        code = "def hello(): return 'world'"
        prompt = model.create_prompt(code, filename="test.py", language="python")

        assert "def hello" in prompt
        assert "python" in prompt.lower()
        assert "Code file: test.py" in prompt
        assert "[/INST]" in prompt

    def test_extract_json_valid(self):
        """Test JSON extraction from valid responses."""
        model = CodeReviewModel(device="cpu")

        # Test JSON in code block
        response = '```json\n{"severity": "high", "line_number": 5}\n```'
        result = model._extract_json(response)
        assert result["severity"] == "high"
        assert result["line_number"] == 5

        # Test plain JSON
        response = '{"severity": "low", "category": "style"}'
        result = model._extract_json(response)
        assert result["severity"] == "low"

    def test_extract_json_invalid(self):
        """Test JSON extraction from invalid responses."""
        model = CodeReviewModel(device="cpu")

        response = "This code looks okay, no issues found."
        result = model._extract_json(response)

        # Should fall back to default values
        assert "severity" in result
        assert "_parse_error" in result

    def test_review_code_structure(self):
        """Test that review_code returns expected structure."""
        model = CodeReviewModel(device="cpu")

        code = "x = 1\ny = 2\nprint(x + y)"
        review = model.review_code(code)

        assert "severity" in review
        assert "category" in review
        assert "suggestion" in review
        assert "explanation" in review
        assert "_raw_response" in review

    def test_review_code_with_language(self):
        """Test review with different languages."""
        model = CodeReviewModel(device="cpu")

        # Python
        review = model.review_code("print('hello')", language="python")
        assert "severity" in review

        # C++ (should still work, model might not be specialized)
        review = model.review_code("int main() { return 0; }", language="cpp")
        assert "severity" in review


class TestBatchReview:
    """Tests for batch_review method."""

    def test_batch_review_multiple_files(self):
        """Test reviewing multiple files."""
        model = CodeReviewModel(device="cpu")

        files = [
            {"code": "def a(): pass", "filename": "a.py"},
            {"code": "def b(): return 1", "filename": "b.py"},
        ]

        results = model.batch_review(files)

        assert len(results) == 2
        for result in results:
            assert "severity" in result

    def test_batch_review_with_errors(self):
        """Test batch review handles individual failures gracefully."""
        model = CodeReviewModel(device="cpu")

        files = [
            {"code": "valid code", "filename": "good.py"},
            {"code": "", "filename": "empty.py"},  # Might cause issues
        ]

        results = model.batch_review(files)
        assert len(results) == 2
        # Even if one fails, should return result with error flag
        for r in results:
            assert "severity" in r


def test_prompt_templates_exist():
    """Test that all prompt template files exist."""
    base_path = Path(__file__).parent.parent / "prompts"
    assert (base_path / "python.txt").exists()
    assert (base_path / "ros2.txt").exists()
    assert (base_path / "ml.txt").exists()


def test_config_yaml_exists():
    """Test that config file exists."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    assert config_path.exists()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
