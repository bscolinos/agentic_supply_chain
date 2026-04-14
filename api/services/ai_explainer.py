"""
AI Explainer service for the NERVE project.

Uses the SingleStore-hosted Claude model via AWS Bedrock-compatible API
to generate data-grounded, citation-heavy explanations of logistics
disruptions, risk scores, and recommended interventions.
"""

import asyncio
import os
import logging
from typing import Any, AsyncGenerator

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = os.getenv("MODEL_NAME", "claude-sonnet-4-5-79066")
MODEL_API_ENDPOINT = os.getenv("MODEL_API_ENDPOINT", "")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")

MAX_TOKENS_EXPLANATION = 500
MAX_TOKENS_NOTIFICATION = 150
TEMPERATURE = 0.3
TIMEOUT_SECONDS = 10
MAX_RETRIES = 1
RATE_LIMIT_BACKOFF = 2

# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client = None
_disabled: bool = False


def _inject_headers(request: Any, **_ignored: Any) -> None:
    """Inject Bearer auth and strip AWS signature headers."""
    request.headers['Authorization'] = f'Bearer {MODEL_API_KEY}'
    request.headers.pop('X-Amz-Date', None)
    request.headers.pop('X-Amz-Security-Token', None)


def _get_client():
    """Return (or create) the shared bedrock-runtime client."""
    global _client
    if _client is None:
        if not MODEL_API_ENDPOINT or not MODEL_API_KEY:
            raise RuntimeError("MODEL_API_ENDPOINT and MODEL_API_KEY must be set")

        cfg = Config(
            signature_version=UNSIGNED,
            read_timeout=TIMEOUT_SECONDS,
            connect_timeout=TIMEOUT_SECONDS,
        )
        _client = boto3.client(
            "bedrock-runtime",
            region_name="us-east-1",
            endpoint_url=MODEL_API_ENDPOINT,
            aws_access_key_id="placeholder",
            aws_secret_access_key="placeholder",
            config=cfg,
        )
        emitter = _client._endpoint._event_emitter
        for event_name in (
            'before-send.bedrock-runtime.Converse',
            'before-send.bedrock-runtime.ConverseStream',
            'before-send.bedrock-runtime.InvokeModel',
            'before-send.bedrock-runtime.InvokeModelWithResponseStream',
        ):
            emitter.register_first(event_name, _inject_headers)
    return _client


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_DISRUPTION_SYSTEM = (
    "You are NERVE, a FedEx logistics disruption analyst. You explain "
    "disruptions to operations managers. Rules:\n"
    "1. ALWAYS cite specific data: tracking numbers, flight numbers, "
    "facility codes (e.g. MEM, IND, SDF), dollar amounts, timestamps.\n"
    "2. Structure your response in four sections: WHAT IS HAPPENING, "
    "WHAT IS AT RISK, WHY IT MATTERS, HISTORICAL PRECEDENT.\n"
    "3. Use short paragraphs. Bold section headers with **markdown**.\n"
    "4. Never say vague things like 'weather may cause delays'. Instead: "
    "'Winter storm URI is producing 8-12in of snow across the Memphis "
    "metro; MEM hub sort operations suspended 0200-1400 CT.'\n"
    "5. Keep the total response under 400 words."
)

_DECISION_SYSTEM = (
    "You are NERVE, a FedEx logistics analyst. Give a concise 2-3 sentence "
    "explanation of the data element the user asks about. Cite every specific "
    "number and identifier in the provided data. Do not generalize."
)

_NOTIFICATION_SYSTEM = (
    "You are writing a customer-facing delivery notification for FedEx. "
    "Tone: proactive, reassuring, specific. One short paragraph, no "
    "markdown. Include the tracking number, new ETA with date and time, "
    "and reroute path if applicable. End with 'No action needed.' if the "
    "customer does not need to do anything."
)


def _build_disruption_prompt(data: dict) -> str:
    """Turn structured disruption data into a user-message prompt."""
    parts = ["Explain this disruption using ONLY the data below.\n"]

    if event := data.get("event"):
        parts.append(f"EVENT: {event}")
    if location := data.get("location"):
        parts.append(f"LOCATION: {location}")
    if time_window := data.get("time_window"):
        parts.append(f"TIME WINDOW: {time_window}")
    if facility := data.get("facility"):
        parts.append(f"FACILITY: {facility}")
    if weather := data.get("weather"):
        parts.append(f"WEATHER DETAILS: {weather}")

    if shipments := data.get("shipments"):
        parts.append(f"AFFECTED SHIPMENTS: {shipments}")
    if priority_breakdown := data.get("priority_breakdown"):
        parts.append(f"PRIORITY BREAKDOWN: {priority_breakdown}")
    if sla_deadlines := data.get("sla_deadlines"):
        parts.append(f"SLA DEADLINES: {sla_deadlines}")

    if risk_scores := data.get("risk_scores"):
        parts.append(f"RISK SCORES: {risk_scores}")
    if cost := data.get("estimated_cost"):
        parts.append(f"ESTIMATED COST: ${cost}")
    if customer_impact := data.get("customer_impact"):
        parts.append(f"CUSTOMER IMPACT: {customer_impact}")

    if historical := data.get("historical"):
        parts.append(f"HISTORICAL PRECEDENT: {historical}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------


def _template_fallback(disruption_data: dict) -> str:
    """Generate a structured explanation from raw data when AI is unavailable."""
    event_name = disruption_data.get("event", "Unknown event")
    facility = disruption_data.get("facility", "unknown facility")
    location = disruption_data.get("location", "")
    time_window = disruption_data.get("time_window", "unknown time window")

    shipments = disruption_data.get("shipments", {})
    total = shipments.get("total", "unknown number of") if isinstance(shipments, dict) else shipments
    critical = (
        shipments.get("critical", "N/A") if isinstance(shipments, dict) else "N/A"
    )

    cost = disruption_data.get("estimated_cost", "unknown")
    risk = disruption_data.get("risk_scores", {})
    overall_risk = risk.get("overall", "N/A") if isinstance(risk, dict) else risk

    location_str = f" in {location}" if location else ""
    return (
        f"Disruption detected: {event_name} affecting {facility}{location_str}. "
        f"{total} shipments at risk ({critical} critical/healthcare). "
        f"Estimated impact: ${cost}. "
        f"Overall risk score: {overall_risk}. "
        f"Time window: {time_window}."
    )


# ---------------------------------------------------------------------------
# Core helpers (sync, run in thread for async)
# ---------------------------------------------------------------------------


def _converse_sync(system: str, user_content: str, max_tokens: int) -> str:
    """Make a synchronous Converse call and return the text response."""
    client = _get_client()
    response = client.converse(
        modelId=MODEL,
        messages=[{"role": "user", "content": [{"text": user_content}]}],
        system=[{"text": system}],
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": TEMPERATURE,
        },
    )
    return response["output"]["message"]["content"][0]["text"]


def _converse_stream_sync(system: str, user_content: str, max_tokens: int):
    """Make a synchronous ConverseStream call, yielding text chunks."""
    client = _get_client()
    response = client.converse_stream(
        modelId=MODEL,
        messages=[{"role": "user", "content": [{"text": user_content}]}],
        system=[{"text": system}],
        inferenceConfig={
            "maxTokens": max_tokens,
            "temperature": TEMPERATURE,
        },
    )
    for event in response["stream"]:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                yield delta["text"]


class _RefusalError(Exception):
    """Internal: raised when Claude refuses or returns unexpected stop."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def explain_disruption(disruption_data: dict) -> AsyncGenerator[str, None]:
    """
    Stream an AI-generated explanation of a logistics disruption.

    Yields text chunks. On ANY failure the generator yields a single
    template-based fallback string.
    """
    global _disabled

    if _disabled:
        yield _template_fallback(disruption_data)
        return

    prompt = _build_disruption_prompt(disruption_data)
    attempts = 0
    last_error: Exception | None = None

    while attempts <= MAX_RETRIES:
        try:
            got_content = False
            # Run the sync streaming call in a thread
            loop = asyncio.get_event_loop()
            chunks = await loop.run_in_executor(
                None,
                lambda: list(_converse_stream_sync(
                    _DISRUPTION_SYSTEM, prompt, MAX_TOKENS_EXPLANATION
                ))
            )
            for chunk in chunks:
                got_content = True
                yield chunk

            if not got_content:
                logger.warning("Model returned empty response for disruption")
                raise _RefusalError("empty response")

            return

        except RuntimeError as exc:
            logger.error("Model config error -- disabling AI: %s", exc)
            _disabled = True
            last_error = exc
            break

        except _RefusalError as exc:
            last_error = exc
            break

        except Exception as exc:
            attempts += 1
            last_error = exc
            logger.warning("Model error (attempt %d): %s", attempts, exc)
            if attempts <= MAX_RETRIES:
                await asyncio.sleep(RATE_LIMIT_BACKOFF)
                continue
            break

    logger.info("Falling back to template (last error: %s)", last_error)
    yield _template_fallback(disruption_data)


async def explain_decision(context: dict) -> AsyncGenerator[str, None]:
    """Stream a concise 2-3 sentence explanation of any data element."""
    global _disabled

    data = context.get("data", {})
    question = context.get("question", "Explain this data.")

    user_content = (
        f"Question: {question}\n\n"
        f"Data: {data}"
    )

    fallback = (
        f"The requested data shows: {data}. "
        f"(AI explanation unavailable; showing raw values.)"
    )

    if _disabled:
        yield fallback
        return

    attempts = 0
    last_error: Exception | None = None

    while attempts <= MAX_RETRIES:
        try:
            got_content = False
            loop = asyncio.get_event_loop()
            chunks = await loop.run_in_executor(
                None,
                lambda: list(_converse_stream_sync(
                    _DECISION_SYSTEM, user_content, MAX_TOKENS_EXPLANATION
                ))
            )
            for chunk in chunks:
                got_content = True
                yield chunk

            if not got_content:
                raise _RefusalError("empty response")

            return

        except RuntimeError as exc:
            logger.error("Model config error -- disabling AI: %s", exc)
            _disabled = True
            last_error = exc
            break

        except _RefusalError as exc:
            last_error = exc
            break

        except Exception as exc:
            attempts += 1
            last_error = exc
            if attempts <= MAX_RETRIES:
                await asyncio.sleep(RATE_LIMIT_BACKOFF)
                continue
            break

    logger.info("Decision fallback (last error: %s)", last_error)
    yield fallback


async def generate_customer_notification(shipment: dict, intervention: dict) -> str:
    """Generate a customer-facing notification message (non-streaming)."""
    global _disabled

    tracking = shipment.get("tracking_number", "your package")
    destination = shipment.get("destination", "")
    new_eta = intervention.get("new_eta", "updated shortly")
    reroute_via = intervention.get("reroute_via", "")
    reason = intervention.get("reason", "potential delays")

    reroute_str = f" via {reroute_via}" if reroute_via else ""
    dest_str = f" to {destination}" if destination else ""
    fallback = (
        f"Your package {tracking} is being proactively rerouted{reroute_str}"
        f"{dest_str} to avoid {reason}. "
        f"New estimated delivery: {new_eta}. No action needed."
    )

    if _disabled:
        return fallback

    user_content = (
        f"Write a customer notification for this shipment.\n\n"
        f"SHIPMENT: {shipment}\n"
        f"INTERVENTION: {intervention}"
    )

    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            lambda: _converse_sync(
                _NOTIFICATION_SYSTEM, user_content, MAX_TOKENS_NOTIFICATION
            )
        )
        if text.strip():
            return text.strip()
        logger.warning("Empty notification response from model")
        return fallback

    except RuntimeError as exc:
        logger.error("Model config error in notification -- disabling AI: %s", exc)
        _disabled = True
        return fallback

    except Exception as exc:
        logger.warning("Notification error: %s", exc)
        return fallback
