"""
NERVE Risk Scoring Service

Scores shipments against active weather events to detect disruptions.
Joins weather events with shipment data, facility data, and SLA deadlines
to produce risk scores (0-100) and trigger disruption detection.
"""

from datetime import datetime, timedelta

from api.services.db import get_connection

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEVERITY_BASE_POINTS = {
    "watch": 20,
    "warning": 50,
    "emergency": 80,
}

PRIORITY_MULTIPLIER = {
    "healthcare": 2.0,
    "critical": 1.5,
    "express": 1.2,
    "standard": 1.0,
}

# Average SLA penalty per shipment (in cents) used for cost estimation
SLA_PENALTY_CENTS = {
    "standard": 5000,       # $50
    "express": 20000,       # $200
    "critical": 50000,      # $500
    "healthcare": 200000,   # $2000
}

# Disruption detection thresholds
MIN_SEVERITY_FOR_DISRUPTION = "warning"  # warning or emergency
MIN_AT_RISK_SHIPMENTS = 10
AT_RISK_SCORE_THRESHOLD = 50


# ---------------------------------------------------------------------------
# score_shipments
# ---------------------------------------------------------------------------

def score_shipments(db):
    """Score all in-transit shipments against active weather events.

    For each active weather event, finds shipments at or routed through
    affected facilities and calculates a composite risk score (0-100).

    Returns:
        dict with keys:
            affected_shipments - list of dicts with shipment details and scores
            count_by_priority  - dict mapping priority to count of affected
            total_at_risk      - int total shipments with score > 0
    """

    # 1. Fetch active weather events
    active_events, _ = db.execute_query(
        """
        SELECT weather_event_id, event_name, event_type, severity,
               affected_facilities, radius_miles, latitude, longitude
        FROM weather_events
        WHERE is_active = 1
        """,
        [],
    )

    if not active_events:
        return {
            "affected_shipments": [],
            "count_by_priority": {},
            "total_at_risk": 0,
        }

    affected_shipments_by_id = {}
    count_by_priority = {}
    now = datetime.utcnow()
    score_updates: dict[int, float] = {}
    event_configs = []
    facility_to_events: dict[str, list[dict]] = {}
    similarity_cache: dict[tuple[str, str], bool] = {}

    for event in active_events:
        facility_codes = _parse_facility_codes(event.get("affected_facilities"))
        if not facility_codes:
            continue

        event_key = (event["event_type"], event["severity"])
        if event_key not in similarity_cache:
            similarity_cache[event_key] = _check_historical_similarity(db, event)

        event_config = {
            "weather_event_id": event["weather_event_id"],
            "weather_event_name": event["event_name"],
            "severity": event["severity"],
            "history_bonus": similarity_cache[event_key],
            "facility_codes": facility_codes,
        }
        event_configs.append(event_config)

        for facility_code in facility_codes:
            facility_to_events.setdefault(facility_code, []).append(event_config)

    if not event_configs:
        return {
            "affected_shipments": [],
            "count_by_priority": {},
            "total_at_risk": 0,
        }

    unique_facility_codes = sorted(facility_to_events.keys())
    placeholders = ", ".join(["%s"] * len(unique_facility_codes))
    shipments_sql = f"""
        SELECT s.shipment_id, s.tracking_number, s.priority, s.status,
               s.sla_deadline, s.current_facility,
               s.origin_facility, s.destination_facility
        FROM shipments s
        WHERE s.status NOT IN ('delivered', 'exception')
          AND (
              s.current_facility IN ({placeholders})
              OR s.origin_facility IN ({placeholders})
              OR s.destination_facility IN ({placeholders})
          )
    """
    shipment_rows, _ = db.execute_query(shipments_sql, unique_facility_codes * 3)

    for shipment in shipment_rows:
        shipment_facilities = {
            shipment.get("current_facility"),
            shipment.get("origin_facility"),
            shipment.get("destination_facility"),
        }
        matching_events = {}
        for facility_code in shipment_facilities:
            if not facility_code:
                continue
            for event in facility_to_events.get(facility_code, []):
                matching_events[event["weather_event_id"]] = event

        if not matching_events:
            continue

        scored_events = []
        for event in matching_events.values():
            score = _calculate_risk_score(
                severity=event["severity"],
                priority=shipment["priority"],
                sla_deadline=shipment["sla_deadline"],
                now=now,
                history_bonus=event["history_bonus"],
            )
            scored_events.append((score, event))

        final_score, primary_event = max(scored_events, key=lambda item: item[0])
        shipment_id = shipment["shipment_id"]
        score_updates[shipment_id] = final_score

        affected_shipments_by_id[shipment_id] = {
            "shipment_id": shipment_id,
            "tracking_number": shipment["tracking_number"],
            "priority": shipment["priority"],
            "status": shipment["status"],
            "current_facility": shipment["current_facility"],
            "sla_deadline": shipment["sla_deadline"],
            "risk_score": final_score,
            "weather_event_id": primary_event["weather_event_id"],
            "weather_event_name": primary_event["weather_event_name"],
        }

        priority = shipment["priority"]
        count_by_priority[priority] = count_by_priority.get(priority, 0) + 1

    # 5. Persist scores: batch into chunks to stay fast over the network.
    if score_updates:
        CHUNK = 500
        with get_connection() as conn:
            cur = conn.cursor()
            score_update_items = list(score_updates.items())
            for i in range(0, len(score_update_items), CHUNK):
                chunk = score_update_items[i : i + CHUNK]
                ids = [shipment_id for shipment_id, _ in chunk]
                placeholders = ", ".join(["%s"] * len(ids))
                # Build a CASE expression so the whole chunk is one round-trip.
                case_expr = " ".join(
                    f"WHEN {shipment_id} THEN {score}"
                    for shipment_id, score in chunk
                )
                cur.execute(
                    f"""
                    UPDATE shipments
                    SET risk_score = CASE shipment_id {case_expr} END
                    WHERE shipment_id IN ({placeholders})
                    """,
                    ids,
                )

    return {
        "affected_shipments": sorted(
            affected_shipments_by_id.values(),
            key=lambda shipment: shipment["risk_score"],
            reverse=True,
        ),
        "count_by_priority": count_by_priority,
        "total_at_risk": len(affected_shipments_by_id),
    }


# ---------------------------------------------------------------------------
# detect_disruptions
# ---------------------------------------------------------------------------

def detect_disruptions(db):
    """Check active weather events and create disruption records when warranted.

    Conditions for a new disruption:
        - Weather event is active AND severity >= warning
        - At least 10 shipments have risk_score > 50
        - No existing active/detected disruption for this weather event

    Returns:
        list of newly created disruption dicts (may be empty).
    """

    # Fetch qualifying weather events (severity warning or emergency)
    events, _ = db.execute_query(
        """
        SELECT weather_event_id, event_name, event_type, severity,
               affected_facilities
        FROM weather_events
        WHERE is_active = 1
          AND severity IN ('warning', 'emergency')
        """,
        [],
    )

    if not events:
        return []

    new_disruptions = []

    for event in events:
        weather_event_id = event["weather_event_id"]
        facility_codes = _parse_facility_codes(event.get("affected_facilities"))

        if not facility_codes:
            continue

        # Check for existing active/detected disruption for this event
        existing, _ = db.execute_query(
            """
            SELECT disruption_id
            FROM disruptions
            WHERE weather_event_id = %s
              AND status IN ('detected', 'active')
            LIMIT 1
            """,
            [weather_event_id],
        )

        if existing:
            continue

        placeholders = ", ".join(["%s"] * len(facility_codes))
        params = [AT_RISK_SCORE_THRESHOLD] + facility_codes * 3
        aggregate_rows, _ = db.execute_query(
            f"""
            SELECT
                COUNT(*) AS total_at_risk,
                AVG(s.risk_score) AS avg_score,
                SUM(CASE WHEN s.priority IN ('critical', 'healthcare') THEN 1 ELSE 0 END) AS critical_count,
                SUM(CASE WHEN s.priority = 'standard' THEN 1 ELSE 0 END) AS standard_count,
                SUM(CASE WHEN s.priority = 'express' THEN 1 ELSE 0 END) AS express_count,
                SUM(CASE WHEN s.priority = 'critical' THEN 1 ELSE 0 END) AS critical_only_count,
                SUM(CASE WHEN s.priority = 'healthcare' THEN 1 ELSE 0 END) AS healthcare_count
            FROM shipments s
            WHERE s.status NOT IN ('delivered', 'exception')
              AND s.risk_score > %s
              AND (
                  s.current_facility IN ({placeholders})
                  OR s.origin_facility IN ({placeholders})
                  OR s.destination_facility IN ({placeholders})
              )
            """,
            params,
        )
        aggregates = aggregate_rows[0] if aggregate_rows else {}
        total_at_risk = int(aggregates.get("total_at_risk") or 0)
        if total_at_risk < MIN_AT_RISK_SHIPMENTS:
            continue

        # Build per-priority counts and estimate cost
        estimated_cost_cents = 0
        delay_probability = 0.8 if event["severity"] == "emergency" else 0.5
        priority_counts = {
            "standard": int(aggregates.get("standard_count") or 0),
            "express": int(aggregates.get("express_count") or 0),
            "critical": int(aggregates.get("critical_only_count") or 0),
            "healthcare": int(aggregates.get("healthcare_count") or 0),
        }
        critical_count = int(aggregates.get("critical_count") or 0)

        for priority, count in priority_counts.items():
            if count <= 0:
                continue
            penalty = SLA_PENALTY_CENTS.get(priority, SLA_PENALTY_CENTS["standard"])
            estimated_cost_cents += int(count * penalty * delay_probability)

        # Estimate delay hours based on severity
        estimated_delay = 12.0 if event["severity"] == "emergency" else 6.0

        avg_risk = float(aggregates.get("avg_score") or 0.0)

        # Pick the primary affected facility (first in the list)
        primary_facility = facility_codes[0] if facility_codes else None

        # Insert the disruption record
        insert_result = db.execute_write(
            """
            INSERT INTO disruptions
                (weather_event_id, disruption_type, status,
                 affected_facility, affected_shipment_count,
                 critical_shipment_count, estimated_delay_hours,
                 estimated_cost_cents, risk_score, detected_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """,
            [
                weather_event_id,
                "weather",
                "detected",
                primary_facility,
                total_at_risk,
                critical_count,
                estimated_delay,
                estimated_cost_cents,
                round(avg_risk, 2),
            ],
        )
        disruption_data = {
            "disruption_id": insert_result.last_insert_id,
            "weather_event_id": weather_event_id,
            "disruption_type": "weather",
            "status": "detected",
            "affected_facility": primary_facility,
            "affected_shipment_count": total_at_risk,
            "critical_shipment_count": critical_count,
            "estimated_delay_hours": estimated_delay,
            "estimated_cost_cents": estimated_cost_cents,
            "risk_score": round(avg_risk, 2),
            "detected_at": datetime.utcnow().isoformat(),
        }
        new_disruptions.append(disruption_data)

    return new_disruptions


# ---------------------------------------------------------------------------
# get_risk_summary
# ---------------------------------------------------------------------------

def get_risk_summary(db):
    """Return a network health summary.

    Returns:
        dict with keys:
            total_in_transit       - int
            shipments_at_risk      - int (risk_score > 50)
            by_priority            - dict mapping priority to
                                     {total, at_risk} counts
            active_disruption_count - int
            top_5_highest_risk     - list of shipment detail dicts
    """

    aggregate_rows, _ = db.execute_query(
        """
        SELECT
            COUNT(*) AS total_in_transit,
            SUM(CASE WHEN risk_score > %s THEN 1 ELSE 0 END) AS shipments_at_risk
        FROM shipments
        WHERE status NOT IN ('delivered', 'exception')
        """,
        [AT_RISK_SCORE_THRESHOLD],
    )
    aggregate = aggregate_rows[0] if aggregate_rows else {}
    total_in_transit = int(aggregate.get("total_in_transit") or 0)
    shipments_at_risk = int(aggregate.get("shipments_at_risk") or 0)

    priority_rows, _ = db.execute_query(
        """
        SELECT priority,
               COUNT(*) AS total,
               SUM(CASE WHEN risk_score > %s THEN 1 ELSE 0 END) AS at_risk
        FROM shipments
        WHERE status NOT IN ('delivered', 'exception')
        GROUP BY priority
        """,
        [AT_RISK_SCORE_THRESHOLD],
    )
    by_priority = {}
    for row in priority_rows:
        by_priority[row["priority"]] = {
            "total": row["total"],
            "at_risk": int(row["at_risk"]),
        }

    # Active disruption count
    disruption_rows, _ = db.execute_query(
        """
        SELECT COUNT(*) AS cnt
        FROM disruptions
        WHERE status IN ('detected', 'active', 'mitigating')
        """,
        [],
    )
    active_disruption_count = disruption_rows[0]["cnt"] if disruption_rows else 0

    # Top 5 highest risk shipments
    top5_rows, _ = db.execute_query(
        """
        SELECT s.shipment_id, s.tracking_number, s.priority, s.status,
               s.current_facility, s.sla_deadline, s.risk_score,
               s.customer_name, s.declared_value_cents,
               f.facility_name AS current_facility_name,
               f.city AS current_facility_city,
               f.state AS current_facility_state
        FROM shipments s
        LEFT JOIN facilities f ON s.current_facility = f.facility_code
        WHERE s.status NOT IN ('delivered', 'exception')
        ORDER BY s.risk_score DESC
        LIMIT 5
        """,
        [],
    )

    top_5 = []
    for row in top5_rows:
        top_5.append({
            "shipment_id": row["shipment_id"],
            "tracking_number": row["tracking_number"],
            "priority": row["priority"],
            "status": row["status"],
            "current_facility": row["current_facility"],
            "current_facility_name": row.get("current_facility_name"),
            "current_facility_city": row.get("current_facility_city"),
            "current_facility_state": row.get("current_facility_state"),
            "sla_deadline": row["sla_deadline"],
            "risk_score": float(row["risk_score"]),
            "customer_name": row["customer_name"],
            "declared_value_cents": row["declared_value_cents"],
        })

    return {
        "total_in_transit": total_in_transit,
        "shipments_at_risk": shipments_at_risk,
        "by_priority": by_priority,
        "active_disruption_count": active_disruption_count,
        "top_5_highest_risk": top_5,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_facility_codes(affected_facilities_json):
    """Extract a list of facility code strings from the JSON column value.

    The column may be a raw JSON string, an already-parsed list, or None.
    """
    if affected_facilities_json is None:
        return []

    if isinstance(affected_facilities_json, list):
        return [str(code) for code in affected_facilities_json]

    if isinstance(affected_facilities_json, str):
        import json
        try:
            parsed = json.loads(affected_facilities_json)
            if isinstance(parsed, list):
                return [str(code) for code in parsed]
        except (json.JSONDecodeError, TypeError):
            pass

    return []


def _calculate_risk_score(severity, priority, sla_deadline, now, history_bonus):
    """Compute a 0-100 risk score for a single shipment.

    Components:
        - Severity base points (watch=20, warning=50, emergency=80)
        - Priority multiplier (healthcare=2.0, critical=1.5, express=1.2, standard=1.0)
        - SLA urgency bonus (<4h=+20, <8h=+10, <12h=+5)
        - Historical similarity bonus (+10 if similar past disruptions)
    """
    base = SEVERITY_BASE_POINTS.get(severity, 20)
    multiplier = PRIORITY_MULTIPLIER.get(priority, 1.0)

    # SLA urgency
    sla_bonus = 0
    if sla_deadline:
        if isinstance(sla_deadline, str):
            try:
                sla_deadline = datetime.fromisoformat(sla_deadline)
            except ValueError:
                sla_deadline = None

        if sla_deadline:
            hours_remaining = (sla_deadline - now).total_seconds() / 3600
            if hours_remaining < 4:
                sla_bonus = 20
            elif hours_remaining < 8:
                sla_bonus = 10
            elif hours_remaining < 12:
                sla_bonus = 5

    raw_score = (base * multiplier) + sla_bonus + (10 if history_bonus else 0)

    # Clamp to 0-100
    return round(min(max(raw_score, 0), 100), 2)


def _check_historical_similarity(db, event):
    """Return True if similar past disruptions caused delays.

    Looks for disruption_history records matching the same weather type and
    severity that resulted in meaningful delays (> 2 hours).
    """
    rows, _ = db.execute_query(
        """
        SELECT COUNT(*) AS cnt
        FROM disruption_history
        WHERE weather_type = %s
          AND severity = %s
          AND delay_hours > 2
        LIMIT 1
        """,
        [event["event_type"], event["severity"]],
    )
    return rows and rows[0]["cnt"] > 0
