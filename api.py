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
from contextlib import asynccontextmanager
from models.inference import CodeReviewInference

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global model instance
model: Optional[CodeReviewInference] = None
model_loaded = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    global model, model_loaded
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

    try:
        # Run inference in thread pool with timeout (non-blocking)
        review = await asyncio.wait_for(
            asyncio.to_thread(model.generate_review, request.code, request.language),
            timeout=5.0,
        )
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

    for i, snippet in enumerate(request.code_snippets):
        try:
            review = await asyncio.wait_for(
                asyncio.to_thread(
                    model.generate_review, snippet.code, snippet.language
                ),
                timeout=5.0,
            )
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
        "results": results,
        "errors": errors,
    }


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting hipstercheck API server...")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info", timeout_keep_alive=30)
