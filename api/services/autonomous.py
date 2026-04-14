"""
NERVE Autonomous Processing Loop

Background asyncio task that continuously monitors for new weather events,
detects disruptions, generates intervention options, auto-selects the best
option, and executes it — all without operator intervention.
"""

import asyncio
import logging
import os
from datetime import datetime

from api.services.risk_scorer import score_shipments, detect_disruptions
from api.services.intervention import (
    generate_options,
    execute_intervention,
    auto_select_best_option,
)

logger = logging.getLogger(__name__)

loop_interval = int(os.getenv("AUTONOMOUS_LOOP_INTERVAL_SECONDS", "5"))


async def autonomous_loop(app):
    """
    Main autonomous processing loop. Runs every loop_interval seconds.

    1. Score shipments against active weather events
    2. Detect new disruptions
    3. For each new disruption: generate options, auto-select, execute
    4. Broadcast events via WebSocket
    """
    db = app.state.db
    broadcast = app.state.broadcast
    logger.info("Autonomous loop started (interval=%ds)", loop_interval)

    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            logger.info("=== Autonomous cycle #%d starting ===", cycle_count)
            await _run_cycle(db, broadcast)
            logger.info("=== Autonomous cycle #%d complete ===", cycle_count)
        except Exception:
            logger.exception("Autonomous cycle #%d failed", cycle_count)
        await asyncio.sleep(loop_interval)


async def _run_cycle(db, broadcast):
    """Single cycle of the autonomous engine."""

    # 0. Cleanup: deactivate expired weather events
    db.execute_write(
        """
        UPDATE weather_events
        SET is_active = 0
        WHERE is_active = 1
          AND end_time IS NOT NULL
          AND end_time < NOW()
        """
    )

    # 1. Score shipments against active weather
    logger.debug("Step 1: Scoring shipments...")
    loop = asyncio.get_event_loop()
    score_result = await loop.run_in_executor(None, score_shipments, db)
    total_at_risk = score_result.get("total_at_risk", 0)

    if total_at_risk > 0:
        logger.info("Scoring complete: %d shipments at risk", total_at_risk)

    # 2. Detect new disruptions
    logger.debug("Step 2: Detecting new disruptions...")
    new_disruptions = await loop.run_in_executor(None, detect_disruptions, db)
    logger.debug("Found %d new disruptions", len(new_disruptions))

    for disruption in new_disruptions:
        disruption_id = disruption.get("disruption_id")
        if not disruption_id:
            continue

        logger.info("New disruption detected: #%d", disruption_id)

        # Broadcast disruption detection
        await broadcast({
            "type": "disruption_detected",
            "disruption": _serialize(disruption),
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Fire AI explanation (non-blocking, best-effort)
        asyncio.create_task(_generate_explanation(disruption_id))

        # 3. Check if this disruption already has interventions (guard)
        existing, _ = db.execute_query(
            "SELECT intervention_id FROM interventions WHERE disruption_id = %s LIMIT 1",
            (disruption_id,),
        )
        if existing:
            logger.info("Disruption #%d already has interventions, skipping", disruption_id)
            continue

        # 4. Generate intervention options
        try:
            options = await loop.run_in_executor(
                None, generate_options, db, disruption_id
            )
        except Exception:
            logger.exception("Failed to generate options for disruption #%d", disruption_id)
            continue

        if not options:
            continue

        # 5. Auto-select best option
        best = auto_select_best_option(options)
        if not best:
            logger.warning("No viable option for disruption #%d", disruption_id)
            continue

        best_id = best["intervention_id"]
        logger.info(
            "Auto-selected intervention #%d (%s) for disruption #%d",
            best_id, best["option_label"], disruption_id,
        )

        # 6. Execute the intervention
        try:
            result = await loop.run_in_executor(
                None, execute_intervention, db, best_id, "autonomous_engine"
            )
        except Exception:
            logger.exception("Failed to execute intervention #%d", best_id)
            continue

        # 7. Broadcast execution result
        await broadcast({
            "type": "intervention_executed",
            "intervention_id": best_id,
            "disruption_id": disruption_id,
            "option_label": result["option_label"],
            "action_type": result["action_type"],
            "shipments_rerouted": result["shipments_rerouted"],
            "savings_cents": result["estimated_savings_cents"],
            "selected_by": "autonomous_engine",
            "timestamp": datetime.utcnow().isoformat(),
        })

        logger.info(
            "Autonomous: disruption #%d resolved — %s saved, %d shipments rerouted",
            disruption_id,
            result["estimated_savings_cents"],
            result["shipments_rerouted"],
        )

    # 3b. Also check for existing unhandled disruptions (recovery after restart)
    # Limit to 10 per cycle to avoid overwhelming the system on restart
    unhandled, _ = db.execute_query(
        """
        SELECT d.disruption_id
        FROM disruptions d
        WHERE d.status = 'detected'
          AND NOT EXISTS (
              SELECT 1 FROM interventions i WHERE i.disruption_id = d.disruption_id
          )
        LIMIT 10
        """,
    )

    for row in unhandled:
        disruption_id = row["disruption_id"]
        logger.info("Recovering unhandled disruption #%d", disruption_id)

        loop = asyncio.get_event_loop()

        try:
            options = await loop.run_in_executor(
                None, generate_options, db, disruption_id
            )
        except Exception:
            logger.exception("Failed to generate options for recovery disruption #%d", disruption_id)
            continue

        if not options:
            continue

        best = auto_select_best_option(options)
        if not best:
            continue

        try:
            result = await loop.run_in_executor(
                None, execute_intervention, db, best["intervention_id"], "autonomous_engine"
            )
        except Exception:
            logger.exception("Failed to execute recovery intervention for disruption #%d", disruption_id)
            continue

        await broadcast({
            "type": "intervention_executed",
            "intervention_id": best["intervention_id"],
            "disruption_id": disruption_id,
            "option_label": result["option_label"],
            "action_type": result["action_type"],
            "shipments_rerouted": result["shipments_rerouted"],
            "savings_cents": result["estimated_savings_cents"],
            "selected_by": "autonomous_engine",
            "timestamp": datetime.utcnow().isoformat(),
        })


async def _generate_explanation(disruption_id: int):
    """Best-effort AI explanation generation (non-blocking)."""
    try:
        from api.services.ai_explainer import explain_disruption
        # Collect chunks but don't block the main loop
        async for _ in explain_disruption({"disruption_id": disruption_id}):
            pass
    except Exception:
        logger.debug("AI explanation failed for disruption #%d (non-critical)", disruption_id)


def _serialize(obj):
    """Make a dict JSON-serializable (handle datetimes etc.)."""
    result = {}
    for k, v in obj.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result
