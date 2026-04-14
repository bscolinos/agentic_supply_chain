"""AI explanation endpoints with streaming."""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

from api.services.ai_explainer import explain_disruption, explain_decision, generate_customer_notification

router = APIRouter()


@router.get("/explain/disruption/{disruption_id}")
async def explain_disruption_endpoint(disruption_id: int, request: Request):
    """Stream AI explanation for a disruption."""
    db = request.app.state.db

    # Get full disruption context
    disruption, _ = db.execute_query(
        """SELECT d.*, w.event_name, w.event_type as weather_type,
                  w.severity, w.affected_region, w.wind_speed_knots,
                  w.precipitation_inches, w.temperature_f,
                  w.start_time as weather_start, w.end_time as weather_end,
                  w.description as weather_description
           FROM disruptions d
           LEFT JOIN weather_events w ON d.weather_event_id = w.weather_event_id
           WHERE d.disruption_id = %s""",
        (disruption_id,),
    )

    if not disruption:
        raise HTTPException(status_code=404, detail="Disruption not found")

    disruption_data = disruption[0]

    # Get top affected shipments for context
    shipments, _ = db.execute_query(
        """SELECT s.tracking_number, s.priority, s.sla_deadline,
                  s.risk_score, s.customer_name, s.current_facility,
                  f.city, f.state
           FROM shipments s
           LEFT JOIN facilities f ON s.current_facility = f.facility_code
           WHERE s.risk_score > 50
             AND s.current_facility = %s
             AND s.status NOT IN ('delivered', 'exception')
           ORDER BY s.risk_score DESC
           LIMIT 10""",
        (disruption_data.get("affected_facility"),),
    )

    # Get historical similar disruptions
    history, _ = db.execute_query(
        """SELECT disruption_type, weather_type, severity, delay_hours,
                  resolution_action, outcome_description
           FROM disruption_history
           WHERE weather_type = %s AND affected_facility = %s
           ORDER BY created_at DESC
           LIMIT 3""",
        (disruption_data.get("weather_type"), disruption_data.get("affected_facility")),
    )

    d = disruption_data
    context = {
        "event": d.get("event_name") or d.get("weather_type") or "Weather Event",
        "facility": d.get("affected_facility", ""),
        "location": d.get("affected_region", ""),
        "time_window": f"{d.get('weather_start', '')} to {d.get('weather_end', '')}",
        "weather": {
            "type": d.get("weather_type"),
            "severity": d.get("severity"),
            "wind_speed_knots": d.get("wind_speed_knots"),
            "precipitation_inches": d.get("precipitation_inches"),
            "temperature_f": d.get("temperature_f"),
            "description": d.get("weather_description"),
        },
        "shipments": {
            "total": d.get("affected_shipment_count", 0),
            "critical": d.get("critical_shipment_count", 0),
            "top_affected": [
                {
                    "tracking": s.get("tracking_number"),
                    "priority": s.get("priority"),
                    "risk_score": s.get("risk_score"),
                    "facility": f"{s.get('city')}, {s.get('state')}",
                    "sla_deadline": str(s.get("sla_deadline")),
                }
                for s in shipments[:5]
            ],
        },
        "estimated_cost": round((d.get("estimated_cost_cents") or 0) / 100),
        "risk_scores": {"overall": d.get("risk_score", 0)},
        "historical": [
            f"{h.get('disruption_type')} / {h.get('weather_type')} / {h.get('severity')}: "
            f"{h.get('delay_hours')}h delay, resolved via {h.get('resolution_action')}. {h.get('outcome_description')}"
            for h in history
        ],
    }

    async def event_stream():
        async for chunk in explain_disruption(context):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/explain/decision")
async def explain_decision_endpoint(request: Request):
    """Explain any data element or decision."""
    body = await request.json()
    context = body.get("context", {})
    question = body.get("question", "Explain this data point.")

    context["question"] = question

    async def event_stream():
        async for chunk in explain_decision(context):
            yield f"data: {chunk}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/explain/notification-preview")
async def notification_preview(request: Request):
    """Generate customer notification preview."""
    body = await request.json()
    shipment = body.get("shipment", {})
    intervention = body.get("intervention", {})

    notification = await generate_customer_notification(shipment, intervention)

    return {
        "notification": notification,
        "channel": "email",
        "tone": "proactive",
    }
