"""Intervention generation, execution, and reporting endpoints."""

from fastapi import APIRouter, Request, HTTPException

from api.services.intervention import (
    generate_options,
    execute_intervention,
    get_intervention_status,
    get_savings_report,
)

router = APIRouter()


@router.post("/interventions/generate/{disruption_id}")
async def generate_intervention_options(disruption_id: int, request: Request):
    """Generate intervention options for a disruption."""
    db = request.app.state.db

    try:
        options = generate_options(db, disruption_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "disruption_id": disruption_id,
        "options": options,
        "count": len(options),
    }


@router.post("/interventions/execute/{intervention_id}")
async def execute_intervention_endpoint(intervention_id: int, request: Request):
    """Execute a selected intervention."""
    db = request.app.state.db

    # Check if already executed
    existing, _ = db.execute_query(
        "SELECT status FROM interventions WHERE intervention_id = %s",
        (intervention_id,),
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Intervention not found")
    if existing[0]["status"] in ("selected", "executing", "completed"):
        raise HTTPException(status_code=409, detail=f"Intervention already {existing[0]['status']}")

    try:
        result = execute_intervention(db, intervention_id, selected_by="operator")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Broadcast the execution event
    broadcast = request.app.state.broadcast
    await broadcast({
        "type": "intervention_executed",
        "intervention_id": intervention_id,
        "disruption_id": result["disruption_id"],
        "option_label": result["option_label"],
        "shipments_rerouted": result["shipments_rerouted"],
        "savings_cents": result["estimated_savings_cents"],
    })

    return result


@router.get("/interventions/status/{disruption_id}")
async def intervention_status(disruption_id: int, request: Request):
    """Get all interventions and audit trail for a disruption."""
    db = request.app.state.db
    return get_intervention_status(db, disruption_id)


@router.get("/interventions/savings/{intervention_id}")
async def savings_report(intervention_id: int, request: Request):
    """Get the savings report card for a completed intervention."""
    db = request.app.state.db

    try:
        report = get_savings_report(db, intervention_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return report
