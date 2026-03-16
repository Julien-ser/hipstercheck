#!/usr/bin/env python3
"""
Database module for hipstercheck subscription management.

Provides SQLAlchemy models for users, subscriptions, and usage tracking.
Uses SQLite for simplicity with optional PostgreSQL support.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    JSON,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///hipstercheck.db")

# Create engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


class User(Base):
    """User model storing GitHub OAuth information."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(Integer, unique=True, index=True, nullable=False)
    github_username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    usage_tracks = relationship("UsageTrack", back_populates="user")

    def __repr__(self):
        return f"<User(github_id={self.github_id}, username={self.github_username})>"


class Subscription(Base):
    """Subscription model storing Stripe subscription information."""

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    stripe_customer_id = Column(String, index=True)
    stripe_subscription_id = Column(String, unique=True, index=True)
    status = Column(
        String, default="incomplete"
    )  # incomplete, trialing, active, past_due, canceled, unpaid, paused
    plan = Column(String, default="free")  # free, pro
    current_period_start = Column(DateTime)
    current_period_end = Column(DateTime)
    cancel_at_period_end = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="subscription")

    def __repr__(self):
        return f"<Subscription(user_id={self.user_id}, status={self.status}, plan={self.plan})>"

    @property
    def is_active(self) -> bool:
        """Check if subscription is active (paid and not canceled)."""
        return self.status in ["active", "trialing"] and not self.cancel_at_period_end

    @property
    def days_until_expiration(self) -> Optional[int]:
        """Get days until subscription expires."""
        if not self.current_period_end:
            return None
        delta = self.current_period_end - datetime.utcnow()
        return max(0, delta.days)


class UsageTrack(Base):
    """Track user usage for free tier limits."""

    __tablename__ = "usage_tracks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    repo_full_name = Column(String, index=True, nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    # Store additional metadata like file count, scan duration, etc.
    metadata = Column(JSON, default={})

    # Relationships
    user = relationship("User", back_populates="usage_tracks")

    def __repr__(self):
        return f"<UsageTrack(user_id={self.user_id}, repo={self.repo_full_name})>"


def get_db() -> Session:
    """Dependency for FastAPI to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized")


def get_or_create_user(
    db: Session, github_id: int, github_username: str, email: Optional[str] = None
) -> User:
    """
    Get existing user or create new one.

    Args:
        db: Database session
        github_id: GitHub user ID
        github_username: GitHub username
        email: User email (optional)

    Returns:
        User object
    """
    user = db.query(User).filter_by(github_id=github_id).first()
    if not user:
        user = User(github_id=github_id, github_username=github_username, email=email)
        db.add(user)
        db.commit()
        db.refresh(user)

        # Create free subscription record
        subscription = Subscription(
            user_id=user.id, status="inactive", plan="free", current_period_end=None
        )
        db.add(subscription)
        db.commit()
    return user


def get_user_subscription(db: Session, user_id: int) -> Optional[Subscription]:
    """Get user's subscription."""
    return db.query(Subscription).filter_by(user_id=user_id).first()


def update_subscription_from_stripe(
    db: Session,
    user_id: int,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    status: Optional[str] = None,
    plan: Optional[str] = None,
    current_period_start: Optional[datetime] = None,
    current_period_end: Optional[datetime] = None,
    cancel_at_period_end: Optional[bool] = None,
) -> Subscription:
    """
    Update subscription from Stripe webhook data.

    Args:
        db: Database session
        user_id: User ID
        Various Stripe subscription fields

    Returns:
        Updated Subscription object
    """
    subscription = db.query(Subscription).filter_by(user_id=user_id).first()
    if not subscription:
        subscription = Subscription(user_id=user_id)
        db.add(subscription)

    if stripe_customer_id is not None:
        subscription.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id is not None:
        subscription.stripe_subscription_id = stripe_subscription_id
    if status is not None:
        subscription.status = status
    if plan is not None:
        subscription.plan = plan
    if current_period_start is not None:
        subscription.current_period_start = current_period_start
    if current_period_end is not None:
        subscription.current_period_end = current_period_end
    if cancel_at_period_end is not None:
        subscription.cancel_at_period_end = cancel_at_period_end

    subscription.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(subscription)
    return subscription


def track_repo_scan(
    db: Session,
    user_id: int,
    repo_full_name: str,
    metadata: Optional[dict] = None,
) -> UsageTrack:
    """
    Track a repository scan for usage limits.

    Args:
        db: Database session
        user_id: User ID
        repo_full_name: Repository full name (owner/repo)
        metadata: Optional additional data

    Returns:
        UsageTrack object
    """
    usage = UsageTrack(
        user_id=user_id, repo_full_name=repo_full_name, metadata=metadata or {}
    )
    db.add(usage)
    db.commit()
    db.refresh(usage)
    return usage


def get_weekly_scan_count(
    db: Session, user_id: int, since: Optional[datetime] = None
) -> int:
    """
    Get number of repository scans in the past week.

    Args:
        db: Database session
        user_id: User ID
        since: Optional start date (default: 7 days ago)

    Returns:
        Count of scans
    """
    if since is None:
        since = datetime.utcnow() - timedelta(days=7)

    count = (
        db.query(UsageTrack)
        .filter(UsageTrack.user_id == user_id, UsageTrack.scanned_at >= since)
        .count()
    )
    return count


def can_scan_repo(db: Session, user_id: int) -> tuple[bool, str, int]:
    """
    Check if user can scan a repository based on subscription and usage limits.

    Args:
        db: Database session
        user_id: User ID

    Returns:
        Tuple of (can_scan, message, remaining_scans)
    """
    subscription = db.query(Subscription).filter_by(user_id=user_id).first()

    if not subscription:
        # No subscription record - treat as free tier
        subscription = Subscription(user_id=user_id, plan="free", status="incomplete")
        db.add(subscription)
        db.commit()

    # Pro users can scan unlimited repos
    if subscription.plan == "pro" and subscription.is_active:
        return True, "Pro subscription active", 999

    # Free tier: 1 scan per week
    weekly_count = get_weekly_scan_count(db, user_id)
    FREE_TIER_LIMIT = 1

    if weekly_count >= FREE_TIER_LIMIT:
        return (
            False,
            f"Free tier limit reached. You've used {weekly_count}/{FREE_TIER_LIMIT} scans this week. Upgrade to Pro for unlimited scans!",
            0,
        )

    remaining = FREE_TIER_LIMIT - weekly_count
    return True, f"Free tier: {remaining} scan(s) remaining this week", remaining


if __name__ == "__main__":
    init_db()
