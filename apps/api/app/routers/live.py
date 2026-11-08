"""WebSocket live feed: readings and alarm events pushed to the dashboard as JSON."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query, WebSocket, status

from app.core.security import decode_access_token
from app.deps import DbSession
from app.live import Broadcaster, Subscriber, get_broadcaster
from app.models import User

router = APIRouter(tags=["live"])


@router.websocket("/ws/live")
async def live_feed(
    websocket: WebSocket,
    db: DbSession,
    broadcaster: Annotated[Broadcaster, Depends(get_broadcaster)],
    # Browsers cannot set an Authorization header on a WebSocket, so the JWT rides in the query.
    token: Annotated[str, Query()] = "",
    tag_id: Annotated[list[int] | None, Query()] = None,
) -> None:
    """`/ws/live?token=<jwt>&tag_id=1&tag_id=2`. Omit `tag_id` for every tag; alarms always."""
    user_id = decode_access_token(token)
    user = await db.get(User, user_id) if user_id is not None else None
    # Release the pooled DB connection now: a dependency session would otherwise be held open
    # for the whole life of the socket, and a handful of dashboards would exhaust the pool.
    await db.close()
    if user is None:
        # Closing before accept() rejects the handshake (HTTP 403); the socket never opens.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Subscribe before accepting so no event published right after the handshake is missed.
    with broadcaster.subscribe(frozenset(tag_id) if tag_id else None) as sub:
        await websocket.accept()
        await _serve(websocket, sub)


async def _serve(websocket: WebSocket, sub: Subscriber) -> None:
    """Pump queued events out while watching for the client to go away; stop when either ends."""
    tasks = {asyncio.create_task(_send(websocket, sub)), asyncio.create_task(_receive(websocket))}
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    # Collect results so a send to a closed socket doesn't surface as "exception never retrieved".
    await asyncio.gather(*tasks, return_exceptions=True)


async def _send(websocket: WebSocket, sub: Subscriber) -> None:
    while True:
        await websocket.send_json(await sub.queue.get())


async def _receive(websocket: WebSocket) -> None:
    """Server-push only: ignore what the client sends, return when it disconnects."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
