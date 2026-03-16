#!/usr/bin/env python3
"""
hipstercheck - API Tests

Tests for the FastAPI code review microservice.
"""

import pytest
import asyncio
import sys
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from api import app, CodeReviewInference


client = TestClient(app)


class MockInference:
    """Mock inference for testing without real model."""

    def __init__(self):
        self.loaded = True

    def load(self):
        return self

    def generate_review(self, code: str, language: str = "python"):
        """Return a mock review."""
        return {
            "severity": "low",
            "line_number": 1,
            "category": "style",
            "suggestion": "Add type hints for better code clarity",
            "explanation": "Type hints improve code readability and enable static analysis.",
            "code_example": "def hello(name: str) -> str:",
        }

    def batch_generate(self, code_snippets: list, language: str = "python"):
        return [self.generate_review(code, language) for code in code_snippets]


@pytest.fixture(autouse=True)
def mock_model(monkeypatch):
    """Mock the model for all tests that need it."""
    mock = MockInference()
    monkeypatch.setattr("api.model", mock)
    monkeypatch.setattr("api.model_loaded", True)
    return mock


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_check(self):
        """Test health endpoint returns correct structure."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "model_loaded" in data
        assert "uptime" in data
        assert data["status"] in ["healthy", "degraded"]
        assert isinstance(data["model_loaded"], bool)
        assert isinstance(data["uptime"], (int, float))


class TestAnalyzeEndpoint:
    """Tests for /analyze endpoint."""

    def test_analyze_valid_python_code(self):
        """Test analyzing valid Python code."""
        code = """
def hello(name: str) -> str:
    '''Greet someone.'''
    return f"Hello, {name}!"
"""
        response = client.post("/analyze", json={"code": code, "language": "python"})
        assert response.status_code == 200
        data = response.json()
        # Check response structure
        assert "severity" in data
        assert "line_number" in data
        assert "category" in data
        assert "suggestion" in data
        assert "explanation" in data
        # Validate field values
        assert data["severity"] in ["high", "medium", "low", "info", "unknown"]
        assert isinstance(data["line_number"], int)
        assert data["category"] in [
            "bug",
            "optimization",
            "style",
            "security",
            "best_practice",
            "parsing_error",
        ]

    def test_analyze_with_missing_code(self):
        """Test that missing code returns 422."""
        response = client.post("/analyze", json={"language": "python"})
        assert response.status_code == 422  # Validation error

    def test_analyze_with_empty_code(self):
        """Test that empty code returns 422."""
        response = client.post("/analyze", json={"code": "", "language": "python"})
        assert response.status_code == 422

    def test_analyze_with_different_languages(self):
        """Test analyzing different programming languages."""
        test_cases = [
            ("python", "def foo():\n    return 42"),
            ("javascript", "function foo() {\n  return 42;\n}"),
            ("cpp", "int foo() {\n  return 42;\n}"),
        ]
        for lang, code in test_cases:
            response = client.post("/analyze", json={"code": code, "language": lang})
            assert response.status_code == 200
            data = response.json()
            assert "severity" in data

    def test_analyze_timeout(self, monkeypatch):
        """Test that slow analysis returns 504."""

        # Mock generate_review to sleep longer than timeout
        def slow_review(code, lang):
            time.sleep(6)
            return {
                "severity": "low",
                "line_number": 1,
                "category": "style",
                "suggestion": "test",
                "explanation": "test",
            }

        monkeypatch.setattr("api.model.generate_review", slow_review)
        response = client.post(
            "/analyze", json={"code": "def foo(): pass", "language": "python"}
        )
        assert response.status_code == 504
        data = response.json()
        assert "timeout" in data["detail"].lower()

    def test_analyze_exception_handling(self, monkeypatch):
        """Test that exceptions in analysis return 500."""

        def error_review(code, lang):
            raise RuntimeError("Model inference failed")

        monkeypatch.setattr("api.model.generate_review", error_review)
        response = client.post(
            "/analyze", json={"code": "def foo(): pass", "language": "python"}
        )
        assert response.status_code == 500
        data = response.json()
        assert "failed" in data["detail"].lower()


class TestBatchAnalyzeEndpoint:
    """Tests for /analyze/batch endpoint."""

    def test_batch_analyze_valid(self):
        """Test batch analysis with multiple snippets."""
        snippets = [
            {"code": "def foo1(): return 1", "language": "python"},
            {"code": "def foo2(): return 2", "language": "python"},
            {"code": "def foo3(): return 3", "language": "python"},
        ]
        response = client.post("/analyze/batch", json={"code_snippets": snippets})
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "successful" in data
        assert "failed" in data
        assert "results" in data
        assert data["total"] == 3
        assert data["successful"] == 3
        assert data["failed"] == 0

    def test_batch_analyze_empty(self):
        """Test batch analysis with no snippets."""
        response = client.post("/analyze/batch", json={"code_snippets": []})
        assert response.status_code == 400

    def test_batch_analyze_too_many(self):
        """Test batch analysis with too many snippets."""
        snippets = [
            {"code": f"def foo{i}(): pass", "language": "python"} for i in range(100)
        ]
        response = client.post("/analyze/batch", json={"code_snippets": snippets})
        assert response.status_code == 400
        data = response.json()
        assert "Maximum" in data["detail"]

    def test_batch_analyze_with_errors(self, monkeypatch):
        """Test batch analysis when some snippets fail."""
        call_count = 0

        def sometimes_fails(code, lang):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise RuntimeError("Simulated failure")
            return {
                "severity": "low",
                "line_number": 1,
                "category": "style",
                "suggestion": "test",
                "explanation": "test",
            }

        monkeypatch.setattr("api.model.generate_review", sometimes_fails)
        snippets = [
            {"code": f"def foo{i}(): pass", "language": "python"} for i in range(4)
        ]
        response = client.post("/analyze/batch", json={"code_snippets": snippets})
        assert response.status_code == 200
        data = response.json()
        assert data["successful"] + data["failed"] == 4
        assert data["failed"] > 0


class TestErrorHandling:
    """Tests for error handling."""

    def test_invalid_json_request(self):
        """Test invalid JSON in request body."""
        response = client.post("/analyze", data="invalid json")
        assert response.status_code == 422

    def test_method_not_allowed(self):
        """Test that GET on /analyze returns 405."""
        response = client.get("/analyze")
        assert response.status_code == 405

    def test_404_on_unknown_path(self):
        """Test that unknown path returns 404."""
        response = client.get("/unknown")
        assert response.status_code == 404


class TestIntegrationWithInference:
    """Integration tests with mock inference model."""

    @pytest.fixture
    def sample_code(self):
        """Sample Python code for testing."""
        return """
def calculate_average(numbers):
    total = sum(numbers)
    return total / len(numbers)

def process_data(data):
    avg = calculate_average(data)
    if avg > 10:
        return "high"
    else:
        return "low"
"""

    def test_full_analysis_flow(self, sample_code):
        """Test complete analysis flow with mock model."""
        response = client.post(
            "/analyze", json={"code": sample_code, "language": "python"}
        )
        assert response.status_code == 200
        data = response.json()
        # Ensure response is valid JSON with required fields
        assert "severity" in data
        assert "line_number" in data
        assert "suggestion" in data
        assert "explanation" in data

    def test_response_structure_consistency(self, sample_code):
        """Test that all responses have consistent structure."""
        response = client.post(
            "/analyze", json={"code": sample_code, "language": "python"}
        )
        assert response.status_code == 200
        data = response.json()
        # Check all required fields present
        required_fields = [
            "severity",
            "line_number",
            "category",
            "suggestion",
            "explanation",
        ]
        for field in required_fields:
            assert field in data
        # Optional field should be present or None
        assert "code_example" in data or data.get("code_example") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
