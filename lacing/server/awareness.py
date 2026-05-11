"""Yjs Awareness relay (presence/cursors only).

Phase 4-A of the roadmap (BACK-DOC §4.4): we ship Yjs *Awareness* — the
ephemeral channel for cursors, selections, user identity — but **not**
the document-level CRDT. The roadmap explicitly defers doc-CRDT until a
real two-user conflict occurs.

What this module is
-------------------
A pure WebSocket *relay*. Every binary message a client sends is
broadcast to every other client in the same room. The server doesn't
parse the y-protocol payload, doesn't maintain a ``Y.Doc``, doesn't
persist anything. It's a switchboard.

Why a relay rather than full ``y-websocket``
--------------------------------------------
Honoring the full ``y-websocket`` server protocol would require us to
maintain a ``Y.Doc`` state per room and respond to sync messages —
which puts us in doc-CRDT territory we explicitly want to avoid.
By relaying awareness-only traffic we can swap to a real Hocuspocus or
``y-websocket`` server later without changing the client wire format.

Wire format
-----------
The frontend (``lacing-ui/src/lib/awareness.ts``) sends framed binary
messages whose first byte is the y-protocol message-type:

- ``1`` (``MSG_AWARENESS``) — y-protocols/awareness encoded update.
- ``0`` (``MSG_SYNC``) — silently dropped here; we don't sync docs.

The relay forwards every awareness message verbatim to every other
client in the same project room. New connections receive the latest
known awareness state from peers via a one-shot broadcast: the relay
asks each existing connection to re-publish their state by sending
a single ``query`` byte, which the client honors.

Rooms
-----
A room is identified by ``project_id`` (URL path segment). Two browser
tabs hitting ``/ws/awareness/proj-1`` see each other; a tab on
``/ws/awareness/proj-2`` is isolated.

Footprint
---------
~120 LOC, no external deps beyond FastAPI's bundled ``starlette``
WebSocket. If/when doc-CRDT is needed, replace this module with a
Hocuspocus bridge or ``y-py``-based server; the client adapter is the
contract.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Final

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter(tags=["awareness"])


# Y-protocol message types. We only act on AWARENESS (1) and QUERY (a
# lacing-private extension); SYNC (0) and any unknown types are dropped.
MSG_SYNC: Final = 0
MSG_AWARENESS: Final = 1
# Custom: a new client asks existing peers to re-broadcast their state
# so it can populate its local view without waiting for the next periodic
# heartbeat. Lives in the unused y-protocol message-type space (10+).
MSG_AWARENESS_QUERY: Final = 10


class _Room:
    """A set of WebSockets sharing one project_id.

    Broadcasts are best-effort: a send failure marks the connection for
    removal but never blocks the rest of the room.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._members: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._members.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._members.discard(ws)

    def members_snapshot(self) -> list[WebSocket]:
        # Copy under no lock — set iteration order is not relevant and a
        # transient stale view is fine for best-effort broadcast.
        return list(self._members)

    async def broadcast(self, payload: bytes, *, sender: WebSocket) -> None:
        """Send ``payload`` to every connection in the room except ``sender``."""
        dead: list[WebSocket] = []
        for peer in self.members_snapshot():
            if peer is sender:
                continue
            try:
                await peer.send_bytes(payload)
            except Exception as exc:  # broad: any send error → drop peer
                logger.debug("awareness broadcast failed for peer: %s", exc)
                dead.append(peer)
        for ws in dead:
            await self.remove(ws)


class _RoomRegistry:
    """Process-wide map of project_id → _Room.

    Singleton. WebSocket lifecycles are cheap; rooms accumulate as
    projects are joined and are not garbage-collected on emptiness
    (they would just be re-created on next join). This is fine for the
    expected scale (tens of concurrent projects).
    """

    def __init__(self) -> None:
        self._rooms: dict[str, _Room] = defaultdict(lambda: None)  # type: ignore[arg-type]
        self._lock = asyncio.Lock()

    async def get(self, project_id: str) -> _Room:
        async with self._lock:
            existing = self._rooms.get(project_id)
            if existing is None:
                existing = _Room(project_id)
                self._rooms[project_id] = existing
            return existing


_registry = _RoomRegistry()


@router.websocket("/ws/awareness/{project_id}")
async def awareness_endpoint(ws: WebSocket, project_id: str) -> None:
    """Relay awareness messages between every client joined to ``project_id``.

    Lifecycle:

    1. Accept the connection and register it in the room.
    2. Ask existing peers to rebroadcast their state by emitting a
       ``MSG_AWARENESS_QUERY`` byte; peers respond with their current
       awareness state, which the relay forwards back to the new client
       like any other awareness message.
    3. Forward every subsequent ``MSG_AWARENESS`` payload to the rest
       of the room. Drop other types.
    4. On disconnect, deregister and emit a synthetic awareness update
       on the client's behalf — but we can't synthesize one without a
       Y.Doc, so we leave that to client-side timeouts (yjs awareness
       has built-in 30s expiry).
    """
    await ws.accept()
    room = await _registry.get(project_id)
    await room.add(ws)
    logger.info(
        "awareness: connection joined project=%s members=%d",
        project_id,
        len(room.members_snapshot()),
    )

    # Prompt existing peers to re-publish their awareness state to us.
    # The query byte is a single byte; clients reply with their full
    # encoded awareness state, which the relay forwards as a normal
    # awareness message to the rest of the room (including us).
    query_payload = bytes([MSG_AWARENESS_QUERY])
    for peer in room.members_snapshot():
        if peer is ws:
            continue
        try:
            await peer.send_bytes(query_payload)
        except Exception:  # noqa: S110 — best-effort; failed peers self-evict on next broadcast
            pass

    try:
        while True:
            payload = await ws.receive_bytes()
            if not payload:
                continue
            msg_type = payload[0]
            if msg_type == MSG_AWARENESS:
                await room.broadcast(payload, sender=ws)
            elif msg_type == MSG_AWARENESS_QUERY:
                # A client received a query and is forwarding their state.
                # Treat as awareness for relay purposes.
                await room.broadcast(payload, sender=ws)
            else:
                # MSG_SYNC and unknown types: silently drop. We do not
                # support doc-CRDT in Phase 4.
                continue
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 — log + close, don't crash the server
        logger.exception("awareness: error on project=%s", project_id)
    finally:
        await room.remove(ws)
        logger.info(
            "awareness: connection left project=%s members=%d",
            project_id,
            len(room.members_snapshot()),
        )


__all__ = [
    "router",
    "MSG_AWARENESS",
    "MSG_AWARENESS_QUERY",
    "MSG_SYNC",
]
