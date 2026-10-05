import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from jose import jwt
from sqlalchemy import select
from app import models
from app.core.config import settings
from app.core.deps import user_roles
from app.db.session import AsyncSessionLocal

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


class OrderBroadcaster:
    """Tracks open order sockets with user authentication, roles, and strict customer event isolation."""

    def __init__(self):
        # Maps ws -> {"user_id": int, "email": str, "roles": set[str]}
        self.clients: dict[WebSocket, dict] = {}

    async def connect(self, ws: WebSocket, user_info: dict):
        await ws.accept()
        self.clients[ws] = user_info

    def disconnect(self, ws: WebSocket):
        self.clients.pop(ws, None)

    async def _send(self, ws: WebSocket, msg: str):
        try:
            await ws.send_text(msg)
        except Exception:
            self.disconnect(ws)

    async def notify(self, event_type: str, data: dict):
        if not self.clients:
            return
        payload = {"type": event_type, **data}
        msg = json.dumps(payload)

        tasks = []
        for ws, info in list(self.clients.items()):
            roles = info.get("roles", set())
            is_staff = bool(roles & {"super_admin", "admin", "kitchen"})
            order_cust_id = data.get("customer_id")

            # Tenant / Customer isolation rule:
            # 1. Staff (Super Admin, Admin, Kitchen) receives operational order events
            # 2. Customers ONLY receive events for their own orders (Customer A never sees Customer B's orders)
            if is_staff:
                tasks.append(self._send(ws, msg))
            elif order_cust_id is not None and info.get("user_id") == order_cust_id:
                tasks.append(self._send(ws, msg))

        if tasks:
            await asyncio.gather(*tasks)


order_broadcaster = OrderBroadcaster()


@router.websocket("/ws/orders")
async def orders_ws(websocket: WebSocket, token: str | None = Query(None)):
    """Authenticated and role-isolated orders WebSocket.

    Unauthenticated connections are immediately rejected with status 1008.
    Customers only receive events matching their customer_id.
    """
    if not token:
        # Reject unauthenticated connections immediately
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(models.User).where(models.User.email == email))
        if not user or not user.is_active or user.is_blocked:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user_info = {
            "user_id": user.id,
            "email": user.email,
            "roles": user_roles(user),
        }

    await order_broadcaster.connect(websocket, user_info)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("orders ws closed: %s", e)
    finally:
        order_broadcaster.disconnect(websocket)

