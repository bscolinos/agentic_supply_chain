"""Health and status endpoints."""

import time
from datetime import datetime

from fastapi import APIRouter, Request

from api.services.risk_scorer import get_risk_summary

router = APIRouter()


@router.get("/health-pulse")
async def health_pulse(request: Request):
    """Network health overview - the main dashboard data source."""
    db = request.app.state.db

    t0 = time.time()
    summary = get_risk_summary(db)
    risk_summary_ms = (time.time() - t0) * 1000

    active_disruptions = summary.get("active_disruption_count", 0)
    total_query_ms = risk_summary_ms

    return {
        "timestamp": datetime.now().isoformat(),
        "network_health": {
            "total_in_transit": summary.get("total_in_transit", 0),
            "at_risk_count": summary.get("shipments_at_risk", 0),
            "active_disruptions": summary.get("active_disruption_count", 0),
            "priority_breakdown": summary.get("by_priority", {}),
            "top_5_highest_risk": summary.get("top_5_highest_risk", []),
        },
        "active_disruptions": active_disruptions,
        "query_ms": round(total_query_ms, 1),
        "query_detail": {
            "risk_summary_ms": round(risk_summary_ms, 1),
        },
    }


@router.get("/metrics")
async def metrics(request: Request):
    """Live autonomous engine metrics — polled by the dashboard MetricsBar."""
    db = request.app.state.db

    savings_rows, s_ms = db.execute_query(
        "SELECT COALESCE(SUM(estimated_savings_cents), 0) AS total FROM interventions WHERE status = 'completed'"
    )
    total_savings = savings_rows[0]["total"] if savings_rows else 0

    rerouted_rows, r_ms = db.execute_query(
        "SELECT COUNT(*) AS cnt FROM shipment_events WHERE event_type = 'reroute'"
    )
    total_rerouted = rerouted_rows[0]["cnt"] if rerouted_rows else 0

    epm_rows, epm_ms = db.execute_query(
        "SELECT COUNT(*) AS cnt FROM shipment_events WHERE event_timestamp > DATE_SUB(NOW(), INTERVAL 1 MINUTE)"
    )
    events_per_minute = epm_rows[0]["cnt"] if epm_rows else 0

    active_rows, a_ms = db.execute_query(
        "SELECT COUNT(*) AS cnt FROM disruptions WHERE status IN ('detected', 'active', 'mitigating')"
    )
    active_disruptions = active_rows[0]["cnt"] if active_rows else 0

    completed_rows, c_ms = db.execute_query(
        "SELECT COUNT(*) AS cnt FROM interventions WHERE status = 'completed'"
    )
    completed = completed_rows[0]["cnt"] if completed_rows else 0

    total_ms = s_ms + r_ms + epm_ms + a_ms + c_ms

    return {
        "total_savings_cents": int(total_savings),
        "total_shipments_rerouted": total_rerouted,
        "total_interventions_completed": completed,
        "active_disruptions": active_disruptions,
        "events_per_minute": events_per_minute,
        "query_ms": round(total_ms, 1),
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/status")
async def status(request: Request):
    """System health check for pre-demo verification."""
    db = request.app.state.db
    db_ok = False
    db_ms = 0
    try:
        result, db_ms = db.execute_query("SELECT 1 as ok")
        db_ok = bool(result)
    except Exception:
        pass

    events_per_sec = 0
    try:
        result, _ = db.execute_query(
            """SELECT COUNT(*) as cnt FROM shipment_events
               WHERE event_timestamp > DATE_SUB(NOW(), INTERVAL 10 SECOND)"""
        )
        if result:
            events_per_sec = round(result[0]["cnt"] / 10, 1)
    except Exception:
        pass

    ws_clients = len(getattr(request.app.state, "connected_clients", []))

    return {
        "db_connected": db_ok,
        "db_latency_ms": round(db_ms, 1),
        "events_per_second": events_per_sec,
        "claude_api_configured": bool(__import__("os").environ.get("ANTHROPIC_API_KEY")),
        "websocket_clients": ws_clients,
        "timestamp": datetime.now().isoformat(),
    }
