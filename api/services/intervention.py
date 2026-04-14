"""
Intervention engine for the NERVE project.

Generates deterministic intervention options for disruptions, executes
selected interventions, and tracks progress through the audit trail.
All monetary values are in cents. Cost calculations are rules-based;
LLM narratives are layered on separately.
"""

import logging
import math
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cost constants (cents per shipment reroute, by priority tier)
# ---------------------------------------------------------------------------

REROUTE_COST_PER_SHIPMENT: dict[str, int] = {
    "standard": 200_00,
    "express": 350_00,
    "critical": 500_00,
    "healthcare": 800_00,
}

# Percentage of shipments successfully rerouted in a full-reroute scenario
FULL_REROUTE_SUCCESS_RATE = 0.94

# Hours added to ETA when a shipment is rerouted
REROUTE_DELAY_HOURS = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    """Return current UTC time (extracted for testability)."""
    return datetime.utcnow()


def _shipment_priority_breakdown(
    db, disruption_id: int
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    """
    Fetch affected shipments and compute per-priority counts and costs.

    Returns:
        (shipments, count_by_priority, cost_by_priority)
    """
    shipments, _ = db.execute_query(
        """
        SELECT s.shipment_id, s.tracking_number, s.priority,
               s.estimated_arrival, s.sla_deadline, s.customer_email,
               s.declared_value_cents, s.current_facility
        FROM shipments s
        JOIN disruptions d ON s.current_facility = d.affected_facility
        WHERE d.disruption_id = %s
          AND s.status NOT IN ('delivered', 'exception')
        """,
        (disruption_id,),
    )

    count_by_priority: dict[str, int] = {
        "standard": 0,
        "express": 0,
        "critical": 0,
        "healthcare": 0,
    }
    cost_by_priority: dict[str, int] = {
        "standard": 0,
        "express": 0,
        "critical": 0,
        "healthcare": 0,
    }

    for s in shipments:
        p = s["priority"]
        count_by_priority[p] = count_by_priority.get(p, 0) + 1
        cost_by_priority[p] = cost_by_priority.get(p, 0) + REROUTE_COST_PER_SHIPMENT.get(p, 200_00)

    return shipments, count_by_priority, cost_by_priority


# ---------------------------------------------------------------------------
# 1. generate_options
# ---------------------------------------------------------------------------


def generate_options(db, disruption_id: int) -> list[dict]:
    """
    Generate 2-3 intervention options for a detected disruption.

    Each option is written to the ``interventions`` table with
    status='proposed' and returned as a dict.
    """

    # Fetch the disruption itself
    disruption_rows, _ = db.execute_query(
        "SELECT * FROM disruptions WHERE disruption_id = %s",
        (disruption_id,),
    )
    if not disruption_rows:
        raise ValueError(f"Disruption {disruption_id} not found")
    disruption = disruption_rows[0]

    estimated_disruption_cost = disruption.get("estimated_cost_cents", 0) or 0

    # Get per-priority breakdown of affected shipments
    shipments, count_by_priority, cost_by_priority = _shipment_priority_breakdown(
        db, disruption_id
    )
    total_count = len(shipments)
    critical_count = count_by_priority.get("critical", 0) + count_by_priority.get("healthcare", 0)

    # ── Option A: Full Reroute ──────────────────────────────────────────
    full_reroute_cost = sum(cost_by_priority.values())
    full_reroute_saved = math.ceil(total_count * FULL_REROUTE_SUCCESS_RATE)
    full_reroute_savings = max(estimated_disruption_cost - full_reroute_cost, 0)

    option_a = {
        "disruption_id": disruption_id,
        "option_label": "Option A: Full Reroute",
        "option_description": (
            "Reroute all affected shipments through an alternate hub. "
            "Highest cost but protects the maximum number of shipments and SLAs."
        ),
        "action_type": "full_reroute",
        "estimated_cost_cents": full_reroute_cost,
        "estimated_savings_cents": full_reroute_savings,
        "affected_shipment_count": total_count,
        "shipments_saved_count": full_reroute_saved,
        "customer_notifications_count": full_reroute_saved,
    }

    # ── Option B: Priority-Only Reroute ─────────────────────────────────
    priority_reroute_cost = (
        cost_by_priority.get("critical", 0) + cost_by_priority.get("healthcare", 0)
    )
    # Estimated disruption cost attributable to priority shipments only
    # Use the ratio of priority shipments to total as a rough proxy
    if total_count > 0:
        priority_disruption_cost = int(
            estimated_disruption_cost * (critical_count / total_count)
        )
    else:
        priority_disruption_cost = 0
    priority_savings = max(priority_disruption_cost - priority_reroute_cost, 0)
    non_priority_count = total_count - critical_count
    priority_notifications = critical_count + non_priority_count  # everyone gets notified

    option_b = {
        "disruption_id": disruption_id,
        "option_label": "Option B: Priority-Only Reroute",
        "option_description": (
            "Reroute only critical and healthcare shipments through an alternate hub. "
            "Standard and express shipments receive delay notifications."
        ),
        "action_type": "priority_reroute",
        "estimated_cost_cents": priority_reroute_cost,
        "estimated_savings_cents": priority_savings,
        "affected_shipment_count": total_count,
        "shipments_saved_count": critical_count,
        "customer_notifications_count": priority_notifications,
    }

    # ── Option C: Hold and Wait ─────────────────────────────────────────
    option_c = {
        "disruption_id": disruption_id,
        "option_label": "Option C: Hold and Wait",
        "option_description": (
            "No active intervention. Monitor the disruption and wait for "
            "conditions to improve. All shipments receive delay notifications."
        ),
        "action_type": "hold_and_wait",
        "estimated_cost_cents": 0,
        "estimated_savings_cents": 0,
        "affected_shipment_count": total_count,
        "shipments_saved_count": 0,
        "customer_notifications_count": total_count,
    }

    # ── Persist options ─────────────────────────────────────────────────
    option_payloads = (option_a, option_b, option_c)
    for opt in option_payloads:
        db.execute_write(
            """
            INSERT INTO interventions
                (disruption_id, option_label, option_description, action_type,
                 estimated_cost_cents, estimated_savings_cents,
                 affected_shipment_count, shipments_saved_count,
                 customer_notifications_count, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'proposed')
            """,
            (
                opt["disruption_id"],
                opt["option_label"],
                opt["option_description"],
                opt["action_type"],
                opt["estimated_cost_cents"],
                opt["estimated_savings_cents"],
                opt["affected_shipment_count"],
                opt["shipments_saved_count"],
                opt["customer_notifications_count"],
            ),
        )
    rows, _ = db.execute_query(
        """
        SELECT intervention_id, disruption_id, option_label, option_description,
               action_type, estimated_cost_cents, estimated_savings_cents,
               affected_shipment_count, shipments_saved_count,
               customer_notifications_count, status, selected_by
        FROM interventions
        WHERE disruption_id = %s
        ORDER BY intervention_id DESC
        LIMIT 3
        """,
        (disruption_id,),
    )
    options = list(reversed(rows))

    logger.info(
        "Generated %d intervention options for disruption %d",
        len(options),
        disruption_id,
    )
    return options


# ---------------------------------------------------------------------------
# 1b. auto_select_best_option
# ---------------------------------------------------------------------------


def auto_select_best_option(options: list[dict]) -> dict | None:
    """
    Auto-select the best intervention option.

    Strategy: highest estimated_savings_cents, break ties by lowest cost.
    Excludes hold_and_wait unless it's the only option.
    """
    if not options:
        return None

    # Filter out hold_and_wait if there are other options
    active_options = [o for o in options if o.get("action_type") != "hold_and_wait"]
    if not active_options:
        # Only hold_and_wait available — use it
        active_options = options

    # Sort by savings desc, then cost asc
    active_options.sort(
        key=lambda o: (-o.get("estimated_savings_cents", 0), o.get("estimated_cost_cents", 0))
    )

    return active_options[0]


# ---------------------------------------------------------------------------
# 2. execute_intervention
# ---------------------------------------------------------------------------


def execute_intervention(db, intervention_id: int, selected_by: str = "autonomous_engine") -> dict:
    """
    Execute a selected intervention.

    Transitions the intervention through selected -> executing -> completed,
    updates disruption status, reroutes shipments where applicable, creates
    shipment events, and writes a full audit trail.
    """

    # ── Load the intervention ───────────────────────────────────────────
    int_rows, _ = db.execute_query(
        "SELECT * FROM interventions WHERE intervention_id = %s",
        (intervention_id,),
    )
    if not int_rows:
        raise ValueError(f"Intervention {intervention_id} not found")
    intervention = int_rows[0]
    disruption_id = intervention["disruption_id"]

    # ── Load the disruption ─────────────────────────────────────────────
    dis_rows, _ = db.execute_query(
        "SELECT * FROM disruptions WHERE disruption_id = %s",
        (disruption_id,),
    )
    if not dis_rows:
        raise ValueError(f"Disruption {disruption_id} not found")
    disruption = dis_rows[0]
    detected_at = disruption.get("detected_at") or _now()

    now = _now()

    # ── Mark as selected ────────────────────────────────────────────────
    db.execute_write(
        """
        UPDATE interventions
        SET status = 'selected', selected_at = %s, selected_by = %s
        WHERE intervention_id = %s
        """,
        (now, selected_by, intervention_id),
    )

    # Cancel any other proposed options for the same disruption
    db.execute_write(
        """
        UPDATE interventions
        SET status = 'cancelled'
        WHERE disruption_id = %s
          AND intervention_id != %s
          AND status = 'proposed'
        """,
        (disruption_id, intervention_id),
    )

    # ── Mark as executing ───────────────────────────────────────────────
    db.execute_write(
        "UPDATE interventions SET status = 'executing' WHERE intervention_id = %s",
        (intervention_id,),
    )

    # ── Update disruption status ────────────────────────────────────────
    db.execute_write(
        "UPDATE disruptions SET status = 'mitigating' WHERE disruption_id = %s",
        (disruption_id,),
    )

    # ── Reroute shipments (if applicable) ───────────────────────────────
    action_type = intervention["action_type"]
    rerouted_count = 0

    if action_type in ("full_reroute", "priority_reroute"):
        # Determine which shipments to reroute
        if action_type == "full_reroute":
            priority_filter = "('standard', 'express', 'critical', 'healthcare')"
        else:
            priority_filter = "('critical', 'healthcare')"

        rerouted_shipments, _ = db.execute_query(
            f"""
            SELECT s.shipment_id, s.tracking_number, s.priority,
                   s.estimated_arrival, s.current_facility
            FROM shipments s
            JOIN disruptions d ON s.current_facility = d.affected_facility
            WHERE d.disruption_id = %s
              AND s.status NOT IN ('delivered', 'exception')
              AND s.priority IN {priority_filter}
            """,
            (disruption_id,),
        )
        rerouted_count = len(rerouted_shipments)

        if rerouted_shipments:
            eta_updates = []
            event_values = []
            event_params: list[Any] = []

            for shipment in rerouted_shipments:
                current_eta = shipment.get("estimated_arrival")
                if current_eta:
                    new_eta = current_eta + timedelta(hours=REROUTE_DELAY_HOURS)
                else:
                    new_eta = now + timedelta(hours=REROUTE_DELAY_HOURS)

                eta_updates.append((shipment["shipment_id"], new_eta))
                event_values.append("(%s, %s, 'reroute', %s, %s, %s)")
                event_params.extend(
                    [
                        shipment["shipment_id"],
                        shipment["tracking_number"],
                        shipment.get("current_facility"),
                        now,
                        f"Rerouted due to disruption #{disruption_id}. New ETA: {new_eta.isoformat()}",
                    ]
                )

            shipment_case = " ".join(
                f"WHEN {shipment_id} THEN %s" for shipment_id, _ in eta_updates
            )
            shipment_ids = [shipment_id for shipment_id, _ in eta_updates]
            shipment_placeholders = ", ".join(["%s"] * len(shipment_ids))
            db.execute_write(
                f"""
                UPDATE shipments
                SET estimated_arrival = CASE shipment_id {shipment_case} END,
                    updated_at = %s
                WHERE shipment_id IN ({shipment_placeholders})
                """,
                [new_eta for _, new_eta in eta_updates] + [now] + shipment_ids,
            )
            db.execute_write(
                f"""
                INSERT INTO shipment_events
                    (shipment_id, tracking_number, event_type,
                     facility_code, event_timestamp, description)
                VALUES {", ".join(event_values)}
                """,
                event_params,
            )

    # ── Build audit trail ───────────────────────────────────────────────
    option_label = intervention["option_label"]
    notifications_count = intervention["customer_notifications_count"]

    completed_at = _now()
    db.execute_write(
        """
        INSERT INTO audit_trail
            (disruption_id, intervention_id, action_type, description, created_at)
        VALUES
            (%s, %s, %s, %s, %s),
            (%s, %s, %s, %s, %s)
        """,
        (
            disruption_id,
            intervention_id,
            "intervention_selected",
            f"Intervention selected: {option_label}",
            now,
            disruption_id,
            intervention_id,
            "intervention_complete",
            f"Intervention complete: {rerouted_count} shipments rerouted, {notifications_count} notifications queued",
            completed_at,
        ),
    )

    # ── Mark as completed ───────────────────────────────────────────────
    db.execute_write(
        """
        UPDATE interventions
        SET status = 'completed', completed_at = %s
        WHERE intervention_id = %s
        """,
        (completed_at, intervention_id),
    )

    execution_duration = (completed_at - now).total_seconds()

    logger.info(
        "Intervention %d executed: %s | %d shipments rerouted",
        intervention_id,
        option_label,
        rerouted_count,
    )

    return {
        "intervention_id": intervention_id,
        "disruption_id": disruption_id,
        "option_label": option_label,
        "action_type": action_type,
        "status": "completed",
        "shipments_rerouted": rerouted_count,
        "customer_notifications_queued": notifications_count,
        "estimated_savings_cents": intervention["estimated_savings_cents"],
        "selected_at": now.isoformat(),
        "completed_at": completed_at.isoformat(),
        "execution_duration_seconds": round(execution_duration, 2),
    }


# ---------------------------------------------------------------------------
# 3. get_intervention_status
# ---------------------------------------------------------------------------


def get_intervention_status(db, disruption_id: int) -> dict:
    """
    Return all interventions for a disruption along with their audit trail.
    """

    interventions_rows, _ = db.execute_query(
        """
        SELECT intervention_id, disruption_id, option_label, option_description,
               action_type, estimated_cost_cents, estimated_savings_cents,
               affected_shipment_count, shipments_saved_count,
               customer_notifications_count, status, selected_at, completed_at,
               selected_by
        FROM interventions
        WHERE disruption_id = %s
        ORDER BY intervention_id
        """,
        (disruption_id,),
    )

    audit_rows, _ = db.execute_query(
        """
        SELECT audit_id, disruption_id, intervention_id, action_type,
               description, metadata, created_at
        FROM audit_trail
        WHERE disruption_id = %s
        ORDER BY created_at
        """,
        (disruption_id,),
    )

    return {
        "disruption_id": disruption_id,
        "interventions": interventions_rows,
        "audit_trail": audit_rows,
    }


# ---------------------------------------------------------------------------
# 4. get_savings_report
# ---------------------------------------------------------------------------


def get_savings_report(db, intervention_id: int) -> dict:
    """
    Build the savings report card for a completed intervention.

    Returns penalties avoided, shipment counts, notification counts,
    response time, and healthcare shipments protected.
    """

    int_rows, _ = db.execute_query(
        "SELECT * FROM interventions WHERE intervention_id = %s",
        (intervention_id,),
    )
    if not int_rows:
        raise ValueError(f"Intervention {intervention_id} not found")
    intervention = int_rows[0]
    disruption_id = intervention["disruption_id"]

    # Fetch disruption for timing data
    dis_rows, _ = db.execute_query(
        "SELECT detected_at FROM disruptions WHERE disruption_id = %s",
        (disruption_id,),
    )
    detected_at = dis_rows[0]["detected_at"] if dis_rows else None
    completed_at = intervention.get("completed_at")

    # Response time: disruption detected -> intervention completed
    response_time_seconds: float | None = None
    if detected_at and completed_at:
        delta = completed_at - detected_at
        response_time_seconds = round(delta.total_seconds(), 1)

    # Count healthcare shipments protected (rerouted)
    healthcare_rows, _ = db.execute_query(
        """
        SELECT COUNT(*) AS cnt
        FROM shipment_events se
        JOIN shipments s ON se.shipment_id = s.shipment_id
        WHERE se.event_type = 'reroute'
          AND se.description LIKE %s
          AND s.priority = 'healthcare'
        """,
        (f"%disruption #{disruption_id}%",),
    )
    healthcare_protected = (
        healthcare_rows[0]["cnt"] if healthcare_rows else 0
    )

    return {
        "intervention_id": intervention_id,
        "disruption_id": disruption_id,
        "penalties_avoided_cents": intervention["estimated_savings_cents"],
        "shipments_rerouted": intervention["shipments_saved_count"],
        "customer_notifications_sent": intervention["customer_notifications_count"],
        "response_time_seconds": response_time_seconds,
        "healthcare_shipments_protected": healthcare_protected,
    }
