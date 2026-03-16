#!/usr/bin/env python3
"""
hipstercheck - FastAPI Microservice for Code Review

Provides REST API endpoints for AI-powered code review and subscription management.
"""

from fastapi import FastAPI, HTTPException, Depends, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import asyncio
import time
import logging
import hashlib
import stripe
from contextlib import asynccontextmanager
import pickle
import os
import redis
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from database import (
    get_db,
    init_db,
    get_or_create_user,
    get_user_subscription,
    update_subscription_from_stripe,
    track_repo_scan,
    can_scan_repo,
    get_weekly_scan_count,
    UsageTrack,
    User,
    Subscription,
    SessionLocal,
)
from models.inference import CodeReviewInference
from fastapi import Depends

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Global model instance
model: Optional[CodeReviewInference] = None
model_loaded = False


class ReviewCache:
    """Cache for storing review results with Redis/in-memory fallback."""

    def __init__(self, ttl_hours: int = 24):
        self.ttl_seconds = ttl_hours * 3600
        self.hits = 0
        self.misses = 0
        self.redis_url = os.getenv(
            "REDIS_URL", os.getenv("REDIS", "redis://localhost:6379")
        )
        self.use_redis = False
        self._memory_cache: Dict[str, Dict] = {}

        try:
            self.redis_client = redis.from_url(
                self.redis_url, socket_timeout=5, socket_connect_timeout=5
            )
            self.redis_client.ping()
            self.use_redis = True
            logger.info("✅ Review cache connected to Redis")
        except Exception as e:
            logger.info(f"⚠️ Redis not available for review cache: {e}")
            self.redis_client = None

    def _generate_key(self, code: str, language: str) -> str:
        """Generate cache key from code content and language."""
        content = f"{language}:{code}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def get(self, code: str, language: str) -> Optional[Dict]:
        """Retrieve cached review result."""
        key = self._generate_key(code, language)

        # Try Redis first
        if self.use_redis and self.redis_client:
            try:
                data = self.redis_client.get(f"hipstercheck:review:{key}")
                if data:
                    self.hits += 1
                    return pickle.loads(data)
            except Exception as e:
                logger.error(f"Redis get error: {e}")

        # Fallback to memory cache
        if key in self._memory_cache:
            cached = self._memory_cache[key]
            if time.time() - cached["timestamp"] < self.ttl_seconds:
                self.hits += 1
                return cached["data"]
            else:
                # Expired
                del self._memory_cache[key]

        self.misses += 1
        return None

    def set(self, code: str, language: str, review: Dict):
        """Store review result in cache."""
        key = self._generate_key(code, language)
        data_to_store = {"timestamp": time.time(), "data": review}

        # Store in Redis if available
        if self.use_redis and self.redis_client:
            try:
                serialized = pickle.dumps(data_to_store)
                self.redis_client.setex(
                    f"hipstercheck:review:{key}", self.ttl_seconds, serialized
                )
            except Exception as e:
                logger.error(f"Redis set error: {e}")

        # Also store in memory as fallback
        self._memory_cache[key] = data_to_store

    def get_stats(self) -> Dict:
        """Get cache hit/miss statistics."""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0.0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total,
            "hit_rate_pct": round(hit_rate, 2),
            "backend": "redis" if self.use_redis else "memory",
            "memory_cache_size": len(self._memory_cache),
        }

    def clear(self):
        """Clear all cache entries."""
        if self.use_redis and self.redis_client:
            try:
                # Clear all keys with our prefix
                keys = self.redis_client.keys("hipstercheck:review:*")
                if keys:
                    self.redis_client.delete(*keys)
            except Exception as e:
                logger.error(f"Redis clear error: {e}")

        self._memory_cache.clear()
        self.hits = 0
        self.misses = 0


# Global review cache instance
review_cache: Optional[ReviewCache] = None

# Global database session (will be initialized in lifespan)
db: Optional[Session] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    global model, model_loaded, review_cache, db
    # Startup
    try:
        logger.info("Loading code review model...")
        start = time.time()
        model = CodeReviewInference()
        model.load()
        model_loaded = True
        load_time = time.time() - start
        logger.info(f"Model loaded successfully in {load_time:.2f}s")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        model = None
        model_loaded = False

    # Initialize review cache
    review_cache = ReviewCache(ttl_hours=int(os.getenv("CACHE_TTL_HOURS", "24")))

    # Initialize database
    init_db()
    db = SessionLocal()
    logger.info("✅ Database initialized")

    # Set start time for health checks
    app.state.start_time = time.time()

    yield

    # Shutdown
    logger.info("Shutting down API server...")
    if db:
        db.close()


# Create FastAPI app with lifespan
app = FastAPI(
    title="hipstercheck API",
    description="AI-powered code review microservice",
    version="1.0.0",
    lifespan=lifespan,
)


# Pydantic models for request/response
class CodeAnalysisRequest(BaseModel):
    """Request model for single code analysis."""

    code: str = Field(..., description="Source code to analyze", min_length=1)
    language: str = Field(default="python", description="Programming language")
    filename: Optional[str] = Field(
        default=None, description="Optional filename for context"
    )


class BatchAnalysisRequest(BaseModel):
    """Request model for batch code analysis."""

    code_snippets: List[CodeAnalysisRequest] = Field(
        ..., description="List of code snippets to analyze"
    )


class AnalysisResponse(BaseModel):
    """Response model for code analysis."""

    severity: str = Field(..., description="Issue severity: high|medium|low|info")
    line_number: int = Field(..., description="Line number where issue occurs")
    category: str = Field(
        ..., description="Issue category: bug|optimization|style|security|best_practice"
    )
    suggestion: str = Field(..., description="Concise suggestion for improvement")
    explanation: str = Field(..., description="Detailed explanation of the issue")
    code_example: Optional[str] = Field(
        default=None, description="Optional corrected code example"
    )


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    model_loaded: bool
    uptime: float


class CacheStatsResponse(BaseModel):
    """Response model for cache statistics."""

    hits: int
    misses: int
    total_requests: int
    hit_rate_pct: float
    backend: str
    memory_cache_size: int


class SubscriptionStatusResponse(BaseModel):
    """Response model for subscription status."""

    plan: str = Field(..., description="Subscription plan: free or pro")
    status: str = Field(..., description="Subscription status")
    is_active: bool = Field(..., description="Whether subscription is active")
    stripe_subscription_id: Optional[str] = Field(
        default=None, description="Stripe subscription ID"
    )
    current_period_end: Optional[datetime] = Field(
        default=None, description="Subscription renewal date"
    )
    days_remaining: Optional[int] = Field(
        default=None, description="Days until renewal"
    )


class CreateCheckoutSessionRequest(BaseModel):
    """Request model for creating Stripe checkout session."""

    github_user_id: int = Field(..., description="GitHub user ID")
    github_username: str = Field(..., description="GitHub username")
    email: str = Field(..., description="User email")
    success_url: str = Field(..., description="Success URL after checkout")
    cancel_url: str = Field(..., description="Cancel URL after checkout")


class CheckoutSessionResponse(BaseModel):
    """Response model for checkout session."""

    session_id: str = Field(..., description="Stripe checkout session ID")
    checkout_url: str = Field(..., description="URL to redirect user for payment")


class UsageCheckResponse(BaseModel):
    """Response model for usage check."""

    can_scan: bool = Field(..., description="Whether user can scan a repository")
    message: str = Field(..., description="Explanation of the status")
    remaining_scans: int = Field(..., description="Remaining scans for current period")
    subscription_plan: str = Field(..., description="User's subscription plan")
    weekly_usage: int = Field(..., description="Number of scans used this week")


@app.get("/cache/stats", response_model=CacheStatsResponse)
async def cache_stats():
    """Get review cache statistics."""
    if review_cache is None:
        raise HTTPException(status_code=503, detail="Cache not initialized")
    stats = review_cache.get_stats()
    return CacheStatsResponse(**stats)


@app.post("/cache/clear")
async def clear_cache():
    """Clear review cache."""
    if review_cache is None:
        raise HTTPException(status_code=503, detail="Cache not initialized")
    review_cache.clear()
    return {"message": "Cache cleared successfully", "stats": review_cache.get_stats()}


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    uptime = (
        time.time() - app.state.start_time if hasattr(app.state, "start_time") else 0
    )
    return HealthResponse(
        status="healthy" if model_loaded else "degraded",
        model_loaded=model_loaded,
        uptime=uptime,
    )


@app.post("/analyze", response_model=AnalysisResponse)
async def analyze_code(request: CodeAnalysisRequest):
    """
    Analyze a single code snippet.

    Returns a structured code review with severity, line number, category, suggestion, explanation, and optional code example.

    Timeout: 5 seconds per request
    """
    if model is None:
        raise HTTPException(
            status_code=503, detail="Model not loaded. Service temporarily unavailable."
        )

    # Check cache first
    if review_cache:
        cached = review_cache.get(request.code, request.language)
        if cached:
            return cached

    try:
        # Run inference in thread pool with timeout (non-blocking)
        review = await asyncio.wait_for(
            asyncio.to_thread(model.generate_review, request.code, request.language),
            timeout=5.0,
        )

        # Cache the result
        if review_cache:
            review_cache.set(request.code, request.language, review)

        return review

    except asyncio.TimeoutError:
        logger.warning(
            f"Analysis timeout for code snippet (length={len(request.code)})"
        )
        raise HTTPException(
            status_code=504,
            detail="Analysis timeout - code review took longer than 5 seconds",
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@app.post("/analyze/batch")
async def analyze_batch(request: BatchAnalysisRequest):
    """
    Analyze multiple code snippets in batch.

    Returns a list of analysis responses. Each snippet gets its own review.
    Total timeout: 5 seconds per snippet (not per batch)
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    if not request.code_snippets:
        raise HTTPException(status_code=400, detail="No code snippets provided")

    if len(request.code_snippets) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 snippets per batch")

    results = []
    errors = []
    cache_hits = 0

    for i, snippet in enumerate(request.code_snippets):
        # Check cache first
        cached = None
        if review_cache:
            cached = review_cache.get(snippet.code, snippet.language)
            if cached:
                cache_hits += 1
                results.append({"index": i, "review": cached})
                continue

        # Cache miss - run inference
        try:
            review = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_review, snippet.code, snippet.language
                ),
                timeout=5.0,
            )
            # Store in cache
            if review_cache:
                review_cache.set(snippet.code, snippet.language, review)
            results.append({"index": i, "review": review})
        except asyncio.TimeoutError:
            errors.append(
                {
                    "index": i,
                    "error": "timeout",
                    "message": "Analysis timeout for this snippet",
                }
            )
        except Exception as e:
            errors.append({"index": i, "error": "analysis_failed", "message": str(e)})

    return {
        "total": len(request.code_snippets),
        "successful": len(results),
        "failed": len(errors),
        "cache_hits": cache_hits,
        "results": results,
        "errors": errors,
    }


# ========== Stripe Subscription Endpoints ==========


@app.post("/stripe/create-checkout-session")
async def create_checkout_session(
    request: CreateCheckoutSessionRequest, db: Session = Depends(get_db)
):
    """
    Create a Stripe Checkout session for Pro subscription.

    Requires: github_user_id, github_username, email, success_url, cancel_url
    Returns: checkout_url for redirecting user to Stripe
    """
    try:
        # Get or create user
        user = get_or_create_user(
            db,
            github_id=request.github_user_id,
            github_username=request.github_username,
            email=request.email,
        )

        # Get or create Stripe customer
        subscription = get_user_subscription(db, user.id)

        if not subscription:
            subscription = Subscription(
                user_id=user.id, plan="free", status="incomplete"
            )
            db.add(subscription)
            db.commit()
            db.refresh(subscription)

        customer_id = subscription.stripe_customer_id

        # Create Stripe customer if doesn't exist
        if not customer_id:
            try:
                customer = stripe.Customer.create(
                    email=request.email,
                    metadata={
                        "github_user_id": str(request.github_user_id),
                        "github_username": request.github_username,
                    },
                )
                customer_id = customer.id
                subscription.stripe_customer_id = customer_id
                db.commit()
            except stripe.error.StripeError as e:
                logger.error(f"Failed to create Stripe customer: {e}")
                raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

        # Create price for Pro plan ($10/month)
        # In production, you'd create this in Stripe dashboard and use price ID from env
        price_id = os.getenv(
            "STRIPE_PRICE_ID", "price_H5ggYqfDq8fXjU"
        )  # Fallback for testing

        try:
            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=["card"],
                line_items=[
                    {
                        "price": price_id,
                        "quantity": 1,
                    },
                ],
                mode="subscription",
                success_url=request.success_url + "?session_id={CHECKOUT_SESSION_ID}",
                cancel_url=request.cancel_url,
                metadata={
                    "user_id": str(user.id),
                    "github_user_id": str(request.github_user_id),
                },
            )
        except stripe.error.StripeError as e:
            logger.error(f"Failed to create checkout session: {e}")
            raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")

        return CheckoutSessionResponse(
            session_id=checkout_session.id, checkout_url=checkout_session.url
        )

    except Exception as e:
        logger.error(f"Create checkout session failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to create checkout session: {str(e)}"
        )


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Stripe webhook events.

    Processes: checkout.session.completed, customer.subscription.updated, customer.subscription.deleted
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)}")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {str(e)}")

    # Handle the event
    event_type = event["type"]
    event_data = event["data"]["object"]

    logger.info(f"Received Stripe webhook: {event_type}")

    try:
        if event_type == "checkout.session.completed":
            session = event_data
            user_id = int(session.get("metadata", {}).get("user_id"))
            subscription_id = session.get("subscription")

            if user_id and subscription_id:
                # Fetch subscription details from Stripe
                stripe_sub = stripe.Subscription.retrieve(subscription_id)
                update_subscription_from_stripe(
                    db,
                    user_id=user_id,
                    stripe_subscription_id=stripe_sub.id,
                    status=stripe_sub.status,
                    plan="pro",
                    current_period_start=datetime.fromtimestamp(
                        stripe_sub.current_period_start
                    ),
                    current_period_end=datetime.fromtimestamp(
                        stripe_sub.current_period_end
                    ),
                    cancel_at_period_end=stripe_sub.cancel_at_period_end,
                )
                logger.info(f"Updated subscription for user {user_id}: Pro active")

        elif event_type == "customer.subscription.updated":
            subscription = event_data
            customer_id = subscription.get("customer")

            if customer_id:
                # Find user by Stripe customer ID
                user_sub = (
                    db.query(Subscription)
                    .filter_by(stripe_customer_id=customer_id)
                    .first()
                )
                if user_sub:
                    update_subscription_from_stripe(
                        db,
                        user_id=user_sub.user_id,
                        stripe_subscription_id=subscription.id,
                        status=subscription.status,
                        plan="pro"
                        if subscription.plan == "price_H5ggYqfDq8fXjU"
                        else subscription.plan,
                        current_period_start=datetime.fromtimestamp(
                            subscription.current_period_start
                        ),
                        current_period_end=datetime.fromtimestamp(
                            subscription.current_period_end
                        ),
                        cancel_at_period_end=subscription.cancel_at_period_end,
                    )
                    logger.info(
                        f"Updated subscription for user {user_sub.user_id}: {subscription.status}"
                    )

        elif event_type == "customer.subscription.deleted":
            subscription = event_data
            customer_id = subscription.get("customer")

            if customer_id:
                user_sub = (
                    db.query(Subscription)
                    .filter_by(stripe_customer_id=customer_id)
                    .first()
                )
                if user_sub:
                    update_subscription_from_stripe(
                        db,
                        user_id=user_sub.user_id,
                        status="canceled",
                    )
                    logger.info(
                        f"Marked subscription canceled for user {user_sub.user_id}"
                    )

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        # Don't return error to Stripe - they'll retry
        return {"status": "error", "message": str(e)}

    return {"status": "success"}


@app.get("/subscription/status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(github_user_id: int, db: Session = Depends(get_db)):
    """
    Get subscription status for a user by GitHub user ID.

    Query params: github_user_id
    Returns: subscription status, plan, active flags, etc.
    """
    user = db.query(User).filter_by(github_id=github_user_id).first()
    if not user:
        # No user yet - treat as free tier
        return SubscriptionStatusResponse(
            plan="free",
            status="inactive",
            is_active=False,
            stripe_subscription_id=None,
            current_period_end=None,
            days_remaining=0,
        )

    subscription = get_user_subscription(db, user.id)
    if not subscription:
        return SubscriptionStatusResponse(
            plan="free",
            status="inactive",
            is_active=False,
            stripe_subscription_id=None,
            current_period_end=None,
            days_remaining=0,
        )

    days_remaining = subscription.days_until_expiration

    return SubscriptionStatusResponse(
        plan=subscription.plan,
        status=subscription.status,
        is_active=subscription.is_active,
        stripe_subscription_id=subscription.stripe_subscription_id,
        current_period_end=subscription.current_period_end,
        days_remaining=days_remaining,
    )


@app.get("/usage/check", response_model=UsageCheckResponse)
async def check_usage(github_user_id: int, db: Session = Depends(get_db)):
    """
    Check if user can scan a repository based on subscription and usage limits.

    Query params: github_user_id
    Returns: can_scan, message, remaining_scans, subscription_plan, weekly_usage
    """
    user = db.query(User).filter_by(github_id=github_user_id).first()
    if not user:
        # No user yet - free tier
        weekly_count = get_weekly_scan_count(db, user.id) if user else 0
        return UsageCheckResponse(
            can_scan=True,  # Allow first scan
            message="Free tier: 1 scan allowed per week",
            remaining_scans=1,
            subscription_plan="free",
            weekly_usage=weekly_count,
        )

    can_scan, message, remaining = can_scan_repo(db, user.id)
    subscription = get_user_subscription(db, user.id)
    plan = subscription.plan if subscription else "free"

    weekly_usage = get_weekly_scan_count(db, user.id)

    return UsageCheckResponse(
        can_scan=can_scan,
        message=message,
        remaining_scans=remaining,
        subscription_plan=plan,
        weekly_usage=weekly_usage,
    )


class TrackScanRequest(BaseModel):
    """Request model for tracking a repository scan."""

    github_user_id: int = Field(..., description="GitHub user ID")
    repo_full_name: str = Field(..., description="Repository full name")


@app.post("/usage/track")
async def track_scan(request: TrackScanRequest, db: Session = Depends(get_db)):
    """
    Track a repository scan for usage limits.

    This endpoint should be called after a successful repository scan.
    """
    user = db.query(User).filter_by(github_id=request.github_user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Check if this repo was already scanned recently (within 24h) to avoid double-counting
    recent_scan = (
        db.query(UsageTrack)
        .filter(
            UsageTrack.user_id == user.id,
            UsageTrack.repo_full_name == request.repo_full_name,
            UsageTrack.scanned_at >= datetime.utcnow() - timedelta(hours=24),
        )
        .first()
    )

    if recent_scan:
        # Already scanned recently, don't count again
        return {
            "status": "skipped",
            "message": "Already counted recent scan",
            "user_id": user.id,
        }

    # Track new scan
    usage = track_repo_scan(db, user.id, request.repo_full_name)

    # Get updated usage info
    can_scan, message, remaining = can_scan_repo(db, user.id)

    return {
        "status": "tracked",
        "message": "Scan tracked successfully",
        "user_id": user.id,
        "repo": request.repo_full_name,
        "scanned_at": usage.scanned_at.isoformat(),
        "remaining_scans": remaining,
        "can_scan_next": can_scan,
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting hipstercheck API server...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info", timeout_keep_alive=30)

# Vercel serverless handler
from mangum import Mangum

handler = Mangum(app)
default = handler
