"""NERVE: Network Event Response & Visibility Engine - API Server"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.services.db import Database  # noqa: E402 — imported before routes need it
from api.services.autonomous import autonomous_loop
from api.routes.health import router as health_router
from api.routes.disruptions import router as disruptions_router
from api.routes.explain import router as explain_router
from api.routes.interventions import router as interventions_router
from api.routes.query import router as query_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("nerve")

# Global state
db = Database()
connected_clients: list[WebSocket] = []
_autonomous_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown."""
    global _autonomous_task
    logger.info("NERVE starting up")
    db.connect()
    app.state.db = db
    # Make broadcast accessible before starting autonomous loop
    app.state.broadcast = broadcast_event
    app.state.connected_clients = connected_clients
    # Start autonomous processing loop
    _autonomous_task = asyncio.create_task(autonomous_loop(app))
    logger.info("Autonomous processing loop started")
    yield
    logger.info("NERVE shutting down")
    if _autonomous_task:
        _autonomous_task.cancel()
        try:
            await _autonomous_task
        except asyncio.CancelledError:
            pass
    db.close()


app = FastAPI(
    title="NERVE",
    description="Network Event Response & Visibility Engine",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(health_router, prefix="/api", tags=["health"])
app.include_router(disruptions_router, prefix="/api", tags=["disruptions"])
app.include_router(explain_router, prefix="/api", tags=["explain"])
app.include_router(interventions_router, prefix="/api", tags=["interventions"])
app.include_router(query_router, prefix="/api", tags=["query"])


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Live event feed via WebSocket."""
    await websocket.accept()
    connected_clients.append(websocket)
    logger.info(f"WebSocket client connected. Total: {len(connected_clients)}")
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong", "timestamp": datetime.now().isoformat()}))
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(connected_clients)}")
    except Exception:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


async def broadcast_event(event: dict):
    """Broadcast an event to all connected WebSocket clients."""
    if not connected_clients:
        return
    message = json.dumps(event)
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        connected_clients.remove(client)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
