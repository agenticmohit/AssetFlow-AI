import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger("assetflow.realtime")


class FeedbackRealtime:
    """Single-instance WebSocket fan-out for the beta deployment.

    Railway currently runs one web worker, so an in-process registry is enough.
    A multi-instance deployment can replace this class with Redis pub/sub without
    changing route or browser event contracts.
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, asset_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[asset_id].add(websocket)

    def disconnect(self, asset_id: int, websocket: WebSocket) -> None:
        connections = self._connections.get(asset_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(asset_id, None)

    async def broadcast(self, asset_id: int, event: dict) -> None:
        stale: list[WebSocket] = []
        for websocket in tuple(self._connections.get(asset_id, ())):
            try:
                await websocket.send_json(event)
            except Exception as exc:
                stale.append(websocket)
                logger.debug("Dropping unavailable feedback socket: %s", type(exc).__name__)
        for websocket in stale:
            self.disconnect(asset_id, websocket)


feedback_realtime = FeedbackRealtime()
