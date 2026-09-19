import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["realtime"])
logger = logging.getLogger(__name__)


class MenuBroadcaster:
    """Tracks open menu sockets; notify() fans out one message to all.

    Connection keepalive is handled at the protocol level by uvicorn's
    ws ping/pong (every 20s), so idle sockets stay open without app work.
    """

    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def _send(self, ws: WebSocket, msg: str):
        try:
            await ws.send_text(msg)
        except Exception:
            self.clients.discard(ws)

    async def notify(self, event: str = "menu_changed"):
        if not self.clients:
            return
        msg = json.dumps({"type": event})
        # send to all clients concurrently — one slow socket never delays others
        await asyncio.gather(*(self._send(ws, msg) for ws in list(self.clients)))


menu_broadcaster = MenuBroadcaster()


@router.websocket("/ws/menu")
async def menu_ws(websocket: WebSocket):
    await menu_broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # blocks; pings handled by uvicorn
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("menu ws closed: %s", e)
    finally:
        menu_broadcaster.disconnect(websocket)
