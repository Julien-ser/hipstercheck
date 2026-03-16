#!/usr/bin/env python3
"""
hipstercheck - Stripe API Tests

Tests for Stripe subscription and usage endpoints.
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json
import stripe

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from fastapi.testclient import TestClient
from api import app
from database import (
    User,
    Subscription,
    UsageTrack,
    get_or_create_user,
    get_user_subscription,
    can_scan_repo,
    get_weekly_scan_count,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_stripe():
    """Mock Stripe API for all tests."""
    with (
        patch("stripe.Customer") as mock_customer,
        patch("stripe.checkout.Session") as mock_session,
        patch("stripe.Webhook") as mock_webhook,
        patch("stripe.Subscription") as mock_subscription,
    ):
        # Setup mock responses
        mock_customer.create.return_value = Mock(id="cus_test123")
        mock_session.create.return_value = Mock(
            id="cs_test123", url="https://checkout.stripe.com/test"
        )
        mock_subscription.retrieve.return_value = Mock(
            id="sub_test123",
            status="active",
            plan="price_H5ggYqfDq8fXjU",
            current_period_start=int(
                (datetime.utcnow() - timedelta(days=1)).timestamp()
            ),
            current_period_end=int(
                (datetime.utcnow() + timedelta(days=29)).timestamp()
            ),
            cancel_at_period_end=False,
        )

        yield {
            "customer": mock_customer,
            "session": mock_session,
            "webhook": mock_webhook,
            "subscription": mock_subscription,
        }


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    with patch("api.get_db") as mock_get_db:
        session = MagicMock()

        # Mock user query
        mock_user = User(
            id=1, github_id=123, github_username="testuser", email="test@example.com"
        )
        session.query.return_value.filter_by.return_value.first.return_value = mock_user

        # Mock subscription query
        mock_sub = Subscription(
            id=1,
            user_id=1,
            stripe_customer_id="cus_test123",
            stripe_subscription_id="sub_test123",
            status="active",
            plan="free",
            current_period_end=datetime.utcnow() + timedelta(days=7),
        )

        # chain filter_by calls
        def mock_filter_by(**kwargs):
            if "user_id" in kwargs:
                return MagicMock(first=lambda: mock_sub)
            return MagicMock(first=lambda: None)

        session.query.return_value.filter_by.side_effect = mock_filter_by

        mock_get_db.return_value = session
        yield session


class TestSubscriptionStatus:
    """Tests for /subscription/status endpoint."""

    def test_get_subscription_status_existing_user(self, mock_db_session):
        """Test getting subscription status for existing user."""
        response = client.get("/subscription/status?github_user_id=123")
        assert response.status_code == 200
        data = response.json()
        assert "plan" in data
        assert "status" in data
        assert "is_active" in data

    def test_get_subscription_status_new_user(self):
        """Test getting subscription status for non-existing user (treated as free)."""
        with patch("api.get_or_create_user") as mock_create:
            mock_create.return_value = None
            response = client.get("/subscription/status?github_user_id=99999")
            # Should still return a response (free tier)
            assert response.status_code == 200
            data = response.json()
            assert data["plan"] == "free"


class TestUsageCheck:
    """Tests for /usage/check endpoint."""

    def test_check_usage_pro_user(self, mock_db_session):
        """Test usage check for pro user (unlimited)."""
        # Mock subscription as pro
        mock_sub = Subscription(user_id=1, plan="pro", status="active")
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_sub
        )

        response = client.get("/usage/check?github_user_id=123")
        assert response.status_code == 200
        data = response.json()
        assert data["can_scan"] is True
        assert data["subscription_plan"] == "pro"
        assert data["remaining_scans"] == 999

    def test_check_usage_free_tier_with_remaining(self, mock_db_session):
        """Test usage check for free user with scans remaining."""
        # Mock subscription as free
        mock_sub = Subscription(user_id=1, plan="free", status="incomplete")
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_sub
        )

        # Mock can_scan_repo to return True
        with patch("api.can_scan_repo") as mock_can_scan:
            mock_can_scan.return_value = (True, "Free tier: 1 scan remaining", 1)
            response = client.get("/usage/check?github_user_id=123")
            assert response.status_code == 200
            data = response.json()
            assert data["can_scan"] is True
            assert data["remaining_scans"] == 1

    def test_check_usage_free_tier_limit_reached(self, mock_db_session):
        """Test usage check for free user when limit reached."""
        mock_sub = Subscription(user_id=1, plan="free", status="incomplete")
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_sub
        )

        with patch("api.can_scan_repo") as mock_can_scan:
            mock_can_scan.return_value = (
                False,
                "Free tier limit reached. You've used 1/1 scans this week.",
                0,
            )
            response = client.get("/usage/check?github_user_id=123")
            assert response.status_code == 200
            data = response.json()
            assert data["can_scan"] is False
            assert data["remaining_scans"] == 0


class TestCreateCheckoutSession:
    """Tests for /stripe/create-checkout-session endpoint."""

    def test_create_checkout_session_new_customer(self, mock_db_session, mock_stripe):
        """Test creating checkout session for new customer."""
        payload = {
            "github_user_id": 123,
            "github_username": "testuser",
            "email": "test@example.com",
            "success_url": "http://localhost:8501?checkout=success",
            "cancel_url": "http://localhost:8501?checkout=cancel",
        }
        response = client.post("/stripe/create-checkout-session", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "checkout_url" in data

    def test_create_checkout_session_existing_customer(
        self, mock_db_session, mock_stripe
    ):
        """Test creating checkout session for existing customer."""
        # Subscription already has customer_id
        mock_sub = Subscription(
            user_id=1, plan="free", stripe_customer_id="cus_existing"
        )
        mock_db_session.query.return_value.filter_by.return_value.first.return_value = (
            mock_sub
        )

        payload = {
            "github_user_id": 123,
            "github_username": "testuser",
            "email": "test@example.com",
            "success_url": "http://localhost:8501?checkout=success",
            "cancel_url": "http://localhost:8501?checkout=cancel",
        }
        response = client.post("/stripe/create-checkout-session", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "cs_test123"


class TestTrackScan:
    """Tests for /usage/track endpoint."""

    def test_track_scan_success(self, mock_db_session):
        """Test tracking a successful scan."""
        payload = {
            "github_user_id": 123,
            "repo_full_name": "owner/repo",
        }
        response = client.post("/usage/track", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "tracked"
        assert "scanned_at" in data

    def test_track_scan_duplicate(self, mock_db_session):
        """Test tracking same repo twice within 24h (should be skipped)."""
        # Simulate recent scan
        recent = UsageTrack(
            user_id=1,
            repo_full_name="owner/repo",
            scanned_at=datetime.utcnow() - timedelta(hours=1),
        )
        mock_db_session.query.return_value.filter.return_value.filter.return_value.first.return_value = recent

        payload = {
            "github_user_id": 123,
            "repo_full_name": "owner/repo",
        }
        response = client.post("/usage/track", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
