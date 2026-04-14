"""Natural language query endpoint -- proxies to SingleStore Analyst API."""

import os
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
logger = logging.getLogger(__name__)

analyst_api_base = os.getenv("ANALYST_API_URL", "").rstrip("/")
# Strip any endpoint suffix to get the base URL
for suffix in ("/analyst/chat", "/analyst/query"):
    if analyst_api_base.endswith(suffix):
        analyst_api_base = analyst_api_base[:-len(suffix)]
        break
analyst_api_key = os.getenv("ANALYST_API_KEY", "")


async def _call_analyst(message: str, session_id: str | None) -> dict:
    """
    Forward a question to the SingleStore Analyst API.

    Uses /analyst/query endpoint with output_modes=["sql", "data", "text"]
    so the Analyst API generates SQL, executes it, and returns results.
    No local database connection needed.
    """
    query_url = f"{analyst_api_base}/analyst/query"
    payload: dict = {
        "message": message,
        "output_modes": ["sql", "data", "text"],  # Request SQL + executed data + text explanation
    }
    if session_id:
        payload["session_id"] = session_id

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            query_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {analyst_api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        result = response.json()

    # The Analyst API returns: {"results": [{sql, data, chart, text, error}, ...]}
    # We add metadata and return in our format
    return {
        "message": message,
        "session_id": session_id,  # /analyst/query doesn't return session_id in response
        "results": result.get("results", []),
        "timestamp": datetime.now().isoformat(),
    }


@router.post("/query")
async def natural_language_query(request: Request):
    """
    Forward a natural language question to the SingleStore Analyst API.

    The Analyst API handles SQL generation AND execution, so no local DB connection is needed.
    """
    body = await request.json()
    message = (body.get("message") or body.get("question", "")).strip()
    session_id = body.get("session_id")

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    if not analyst_api_base or not analyst_api_key:
        raise HTTPException(
            status_code=503,
            detail="Analyst API not configured. Set ANALYST_API_URL and ANALYST_API_KEY environment variables.",
        )

    try:
        return await _call_analyst(message, session_id)
    except httpx.HTTPStatusError as exc:
        logger.error("Analyst API returned %d: %s", exc.response.status_code, exc.response.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"Analyst API error (HTTP {exc.response.status_code})",
        )
    except httpx.TimeoutException:
        logger.error("Analyst API timed out for: %s", message[:80])
        raise HTTPException(status_code=504, detail="Analyst API request timed out")
    except Exception:
        logger.exception("Unexpected error querying Analyst API")
        raise HTTPException(status_code=500, detail="Failed to process query")
