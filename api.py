#!/usr/bin/env python3
"""
hipstercheck - FastAPI Microservice for Code Review

Provides REST API endpoints for AI-powered code review.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import asyncio
import time
import logging
import hashlib
from contextlib import asynccontextmanager
import pickle
import os
import redis
from models.inference import CodeReviewInference

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    global model, model_loaded, review_cache
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

    # Set start time for health checks
    app.state.start_time = time.time()

    yield

    # Shutdown
    logger.info("Shutting down API server...")


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


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting hipstercheck API server...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info", timeout_keep_alive=30)
