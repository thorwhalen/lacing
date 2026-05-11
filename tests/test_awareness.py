"""Tests for the Yjs Awareness relay.

The relay is content-agnostic — it never parses the y-protocol payload —
so these tests use synthetic byte strings whose first byte is the
documented message-type.

Strategy
--------
``TestClient.websocket_connect`` is synchronous and blocks on
``receive_bytes`` until a message arrives, so we can't directly assert
"this socket got nothing". Instead we use a *sentinel* technique: after
the message that *shouldn't* propagate, send a second message that
*should*. If the second one is the first thing the receiver sees, the
first was correctly dropped or routed elsewhere.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from lacing.server import create_app  # noqa: E402
from lacing.server.awareness import (  # noqa: E402
    MSG_AWARENESS,
    MSG_AWARENESS_QUERY,
    MSG_SYNC,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _aw(payload: bytes = b"\x00\x00") -> bytes:
    """Synthetic awareness message: type byte + opaque payload."""
    return bytes([MSG_AWARENESS]) + payload


def _drain_join_query(ws) -> None:
    """The relay sends a query byte to existing peers when a new client joins.

    That message lands in those peers' inbox but is not relevant to most
    tests, so this helper consumes it. Idempotent: if no query is queued,
    a synthetic awareness message we send next will surface as the first
    real assertion.
    """
    # We don't actually drain here — we use the sentinel pattern instead.
    # This function is a placeholder for documentation; remove if unused.


def test_two_clients_in_same_room_receive_each_others_awareness(client: TestClient) -> None:
    """A → B propagation through the relay."""
    with (
        client.websocket_connect("/ws/awareness/proj-1") as a,
        client.websocket_connect("/ws/awareness/proj-1") as b,
    ):
        # B may receive a join-time query (type 10). Send a sentinel awareness
        # message and assert it eventually arrives in B's stream.
        a.send_bytes(_aw(b"hello-from-a"))
        # Read up to a few messages until we find the sentinel.
        seen: list[bytes] = []
        for _ in range(4):
            msg = b.receive_bytes()
            seen.append(msg)
            if msg == _aw(b"hello-from-a"):
                break
        assert _aw(b"hello-from-a") in seen


def test_clients_in_different_rooms_are_isolated(client: TestClient) -> None:
    """A in proj-1 must not be heard by B in proj-2.

    Sentinel: also open C in proj-2 and send a known message from C; if B's
    first received message is C's (not A's), isolation holds.
    """
    with (
        client.websocket_connect("/ws/awareness/proj-1") as a,
        client.websocket_connect("/ws/awareness/proj-2") as b,
        client.websocket_connect("/ws/awareness/proj-2") as c,
    ):
        a.send_bytes(_aw(b"from-proj-1"))
        c.send_bytes(_aw(b"from-proj-2"))
        # B is in proj-2 with C; B should see C's message but never A's.
        # First non-query message should be C's.
        for _ in range(4):
            msg = b.receive_bytes()
            if msg[0] == MSG_AWARENESS:
                assert msg == _aw(b"from-proj-2")
                return
        pytest.fail("did not receive proj-2 awareness message")


def test_sender_does_not_receive_its_own_message(client: TestClient) -> None:
    """A's own broadcast must not echo back to A.

    Sentinel: B sends a distinct message; A should see B's, not its own.
    """
    with (
        client.websocket_connect("/ws/awareness/proj-1") as a,
        client.websocket_connect("/ws/awareness/proj-1") as b,
    ):
        a.send_bytes(_aw(b"a-says"))
        b.send_bytes(_aw(b"b-says"))
        # First non-query message A receives should be B's, never its own.
        for _ in range(4):
            msg = a.receive_bytes()
            if msg[0] == MSG_AWARENESS:
                assert msg == _aw(b"b-says"), f"unexpected echo: {msg!r}"
                return
        pytest.fail("did not receive peer awareness message")


def test_sync_messages_are_dropped(client: TestClient) -> None:
    """Doc-CRDT (MSG_SYNC) is out of scope for Phase 4-A — the relay must drop it.

    Sentinel: send a sync message followed by an awareness message. The
    receiver should see the awareness message and never the sync one.
    """
    with (
        client.websocket_connect("/ws/awareness/proj-1") as a,
        client.websocket_connect("/ws/awareness/proj-1") as b,
    ):
        a.send_bytes(bytes([MSG_SYNC]) + b"sync-payload")
        a.send_bytes(_aw(b"awareness-after-sync"))
        for _ in range(4):
            msg = b.receive_bytes()
            if msg[0] == MSG_AWARENESS:
                assert msg == _aw(b"awareness-after-sync")
                return
            if msg[0] == MSG_SYNC:
                pytest.fail("relay should not propagate MSG_SYNC")
        pytest.fail("did not receive awareness sentinel")


def test_query_byte_is_relayed(client: TestClient) -> None:
    """Reply payloads tagged MSG_AWARENESS_QUERY must propagate."""
    with (
        client.websocket_connect("/ws/awareness/proj-1") as a,
        client.websocket_connect("/ws/awareness/proj-1") as b,
    ):
        a.send_bytes(bytes([MSG_AWARENESS_QUERY]) + b"reply-state")
        for _ in range(4):
            msg = b.receive_bytes()
            if msg[0] == MSG_AWARENESS_QUERY and msg[1:] == b"reply-state":
                return
        pytest.fail("query reply was not relayed")


def test_three_clients_full_fanout(client: TestClient) -> None:
    """A's awareness should reach both B and C in the same room."""
    with (
        client.websocket_connect("/ws/awareness/proj-1") as a,
        client.websocket_connect("/ws/awareness/proj-1") as b,
        client.websocket_connect("/ws/awareness/proj-1") as c,
    ):
        a.send_bytes(_aw(b"to-b-and-c"))
        for ws in (b, c):
            for _ in range(6):
                msg = ws.receive_bytes()
                if msg == _aw(b"to-b-and-c"):
                    break
            else:
                pytest.fail(f"client did not receive A's message: {ws}")
