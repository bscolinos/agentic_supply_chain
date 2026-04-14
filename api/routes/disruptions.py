"""Disruption detection and detail endpoints."""

from fastapi import APIRouter, Request, HTTPException

from api.services.risk_scorer import score_shipments, detect_disruptions

router = APIRouter()


@router.get("/disruptions")
async def list_disruptions(request: Request):
    """List all active disruptions."""
    db = request.app.state.db

    disruptions, query_ms = db.execute_query(
        """SELECT d.*, w.event_name as weather_event_name, w.event_type as weather_type,
                  w.severity as weather_severity, w.affected_region,
                  w.wind_speed_knots, w.precipitation_inches, w.temperature_f,
                  w.start_time as weather_start, w.end_time as weather_end
           FROM disruptions d
           LEFT JOIN weather_events w ON d.weather_event_id = w.weather_event_id
           WHERE d.status IN ('detected', 'active', 'mitigating')
           ORDER BY d.risk_score DESC"""
    )

    interventions_by_disruption = {}
    extra_query_ms = 0.0
    disruption_ids = [row["disruption_id"] for row in disruptions]
    if disruption_ids:
        placeholders = ", ".join(["%s"] * len(disruption_ids))
        intervention_rows, interventions_ms = db.execute_query(
            f"""
            SELECT intervention_id, disruption_id, option_label, option_description,
                   action_type, estimated_cost_cents, estimated_savings_cents,
                   affected_shipment_count, shipments_saved_count,
                   customer_notifications_count, status, selected_at, completed_at,
                   selected_by
            FROM interventions
            WHERE disruption_id IN ({placeholders})
            ORDER BY disruption_id, intervention_id
            """,
            disruption_ids,
        )
        extra_query_ms += interventions_ms

        healthcare_rows, healthcare_ms = db.execute_query(
            f"""
            SELECT d.disruption_id, COUNT(*) AS cnt
            FROM shipment_events se
            JOIN shipments s ON se.shipment_id = s.shipment_id
            JOIN disruptions d ON se.description LIKE CONCAT('%%disruption #', d.disruption_id, '%%')
            WHERE se.event_type = 'reroute'
              AND s.priority = 'healthcare'
              AND d.disruption_id IN ({placeholders})
            GROUP BY d.disruption_id
            """,
            disruption_ids,
        )
        extra_query_ms += healthcare_ms

        disruption_lookup = {row["disruption_id"]: row for row in disruptions}
        healthcare_counts = {
            row["disruption_id"]: row["cnt"] for row in healthcare_rows
        }

        for intervention in intervention_rows:
            disruption_id = intervention["disruption_id"]
            entry = interventions_by_disruption.setdefault(
                disruption_id,
                {"interventions": [], "savings_report": None},
            )
            entry["interventions"].append(intervention)

            if intervention["status"] == "completed" and entry["savings_report"] is None:
                disruption = disruption_lookup.get(disruption_id, {})
                detected_at = disruption.get("detected_at")
                completed_at = intervention.get("completed_at")
                response_time_seconds = None
                if detected_at and completed_at:
                    response_time_seconds = round(
                        (completed_at - detected_at).total_seconds(), 1
                    )

                entry["savings_report"] = {
                    "intervention_id": intervention["intervention_id"],
                    "disruption_id": disruption_id,
                    "penalties_avoided_cents": intervention["estimated_savings_cents"],
                    "shipments_rerouted": intervention["shipments_saved_count"],
                    "customer_notifications_sent": intervention["customer_notifications_count"],
                    "response_time_seconds": response_time_seconds,
                    "healthcare_shipments_protected": healthcare_counts.get(disruption_id, 0),
                }

    return {
        "disruptions": disruptions,
        "interventions_by_disruption": interventions_by_disruption,
        "count": len(disruptions),
        "query_ms": round(query_ms + extra_query_ms, 1),
    }


@router.get("/disruptions/{disruption_id}")
async def get_disruption(disruption_id: int, request: Request):
    """Get detailed disruption info including affected shipments."""
    db = request.app.state.db

    # Get disruption
    disruption, d_ms = db.execute_query(
        """SELECT d.*, w.event_name as weather_event_name, w.event_type as weather_type,
                  w.severity as weather_severity, w.affected_region,
                  w.wind_speed_knots, w.precipitation_inches, w.temperature_f,
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

    # Get affected shipments
    affected, s_ms = db.execute_query(
        """SELECT s.shipment_id, s.tracking_number, s.priority, s.status,
                  s.sla_deadline, s.estimated_arrival, s.risk_score,
                  s.customer_name, s.customer_email, s.declared_value_cents,
                  s.origin_facility, s.destination_facility, s.current_facility,
                  f_origin.city as origin_city, f_dest.city as dest_city,
                  f_curr.city as current_city
           FROM shipments s
           LEFT JOIN facilities f_origin ON s.origin_facility = f_origin.facility_code
           LEFT JOIN facilities f_dest ON s.destination_facility = f_dest.facility_code
           LEFT JOIN facilities f_curr ON s.current_facility = f_curr.facility_code
           WHERE s.risk_score > 50
             AND s.current_facility = %s
             AND s.status NOT IN ('delivered', 'exception')
           ORDER BY s.risk_score DESC, s.priority DESC
           LIMIT 100""",
        (disruption_data.get("affected_facility"),),
    )

    # Priority breakdown
    priority_counts = {"standard": 0, "express": 0, "critical": 0, "healthcare": 0}
    for s in affected:
        p = s.get("priority", "standard")
        if p in priority_counts:
            priority_counts[p] += 1

    # Get interventions if any
    interventions, i_ms = db.execute_query(
        """SELECT * FROM interventions
           WHERE disruption_id = %s
           ORDER BY intervention_id""",
        (disruption_id,),
    )

    # Get audit trail (limit to last 20 entries for performance)
    audit, a_ms = db.execute_query(
        """SELECT * FROM audit_trail
           WHERE disruption_id = %s
           ORDER BY created_at DESC
           LIMIT 20""",
        (disruption_id,),
    )
    # Reverse to show oldest first
    audit = list(reversed(audit))

    total_ms = d_ms + s_ms + i_ms + a_ms

    return {
        "disruption": disruption_data,
        "affected_shipments": affected,
        "affected_count": len(affected),
        "priority_breakdown": priority_counts,
        "interventions": interventions,
        "audit_trail": audit,
        "query_ms": round(total_ms, 1),
        "query_detail": {
            "disruption_ms": round(d_ms, 1),
            "shipments_ms": round(s_ms, 1),
            "interventions_ms": round(i_ms, 1),
            "audit_ms": round(a_ms, 1),
            "tables_joined": 6,
            "rows_scanned": f"{len(affected)}+ shipments across 3 facility lookups",
        },
    }


@router.post("/disruptions/detect")
async def run_detection(request: Request):
    """Manually trigger disruption detection cycle."""
    import time

    db = request.app.state.db

    t0 = time.time()
    score_result = score_shipments(db)
    score_ms = (time.time() - t0) * 1000

    t1 = time.time()
    new_disruptions = detect_disruptions(db)
    detect_ms = (time.time() - t1) * 1000

    if new_disruptions:
        broadcast = request.app.state.broadcast
        for d in new_disruptions:
            await broadcast({
                "type": "disruption_detected",
                "disruption": d,
                "timestamp": d.get("detected_at", ""),
            })

    return {
        "shipments_scored": len(score_result.get("affected_shipments", [])),
        "shipments_at_risk": score_result.get("total_at_risk", 0),
        "new_disruptions": new_disruptions,
        "query_ms": round(score_ms + detect_ms, 1),
    }
