"""Tests for ``lacing.oplog`` and the ``/oplog`` + ``/state-at`` endpoints."""

from __future__ import annotations

from uuid import uuid4

import pytest

from lacing.oplog import InMemoryOpLog, OpLogEntry, SqliteOpLog, replay


# ---------------------------------------------------------------------------
# OpLogEntry round-trip
# ---------------------------------------------------------------------------


class TestOpLogEntry:
    def test_to_from_dict(self):
        entry = OpLogEntry(
            clock=1,
            operation="add_annotation",
            target_id=str(uuid4()),
            payload={"annotation": {"id": "x"}},
            actor="user:thor",
            received_at=1700000000.0,
        )
        d = entry.to_dict()
        rt = OpLogEntry.from_dict(d)
        assert rt == entry


# ---------------------------------------------------------------------------
# InMemoryOpLog
# ---------------------------------------------------------------------------


class TestInMemoryOpLog:
    def test_empty(self):
        log = InMemoryOpLog()
        assert len(log) == 0
        assert log.latest_clock() == 0
        assert list(log.entries()) == []

    def test_append_returns_monotonic_clocks(self):
        log = InMemoryOpLog()
        c1 = log.append("add_tier", target_id="words", payload={"name": "words"})
        c2 = log.append("add_tier", target_id="phon", payload={"name": "phon"})
        c3 = log.append("set_meta", target_id="rate", payload={"value": "1000"})
        assert c1 == 1
        assert c2 == 2
        assert c3 == 3
        assert log.latest_clock() == 3
        assert len(log) == 3

    def test_entries_full(self):
        log = InMemoryOpLog()
        log.append("a")
        log.append("b")
        log.append("c")
        ops = [e.operation for e in log.entries()]
        assert ops == ["a", "b", "c"]

    def test_entries_until_clock(self):
        log = InMemoryOpLog()
        for op in ["a", "b", "c", "d"]:
            log.append(op)
        ops = [e.operation for e in log.entries(until_clock=2)]
        assert ops == ["a", "b"]

    def test_entries_from_clock(self):
        log = InMemoryOpLog()
        for op in ["a", "b", "c", "d"]:
            log.append(op)
        ops = [e.operation for e in log.entries(from_clock=3)]
        assert ops == ["c", "d"]

    def test_actor_default_anonymous(self):
        log = InMemoryOpLog()
        log.append("x")
        e = next(log.entries())
        assert e.actor == "anonymous"


# ---------------------------------------------------------------------------
# SqliteOpLog
# ---------------------------------------------------------------------------


class TestSqliteOpLog:
    def test_empty(self):
        log = SqliteOpLog(":memory:", check_same_thread=False)
        try:
            assert len(log) == 0
            assert log.latest_clock() == 0
        finally:
            log.close()

    def test_append_persists(self, tmp_path):
        path = tmp_path / "oplog.db"
        log = SqliteOpLog(str(path))
        try:
            log.append("a", target_id="x", payload={"k": 1})
            log.append("b", target_id="y", payload={"k": 2})
        finally:
            log.close()

        # Reopen and confirm we still see both entries.
        log2 = SqliteOpLog(str(path))
        try:
            assert len(log2) == 2
            ops = [(e.operation, e.target_id, e.payload) for e in log2.entries()]
            assert ops == [("a", "x", {"k": 1}), ("b", "y", {"k": 2})]
        finally:
            log2.close()

    def test_clock_filters(self):
        log = SqliteOpLog(":memory:", check_same_thread=False)
        try:
            for op in ["a", "b", "c", "d"]:
                log.append(op)
            assert [e.operation for e in log.entries(until_clock=2)] == ["a", "b"]
            assert [e.operation for e in log.entries(from_clock=3)] == ["c", "d"]
        finally:
            log.close()


# ---------------------------------------------------------------------------
# replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_empty_yields_empty_store(self):
        log = InMemoryOpLog()
        store = replay(log)
        assert len(list(store.all())) == 0

    def test_replay_add_tier(self):
        from lacing.tier import Tier, TierStereotype

        log = InMemoryOpLog()
        log.append(
            "add_tier",
            target_id="words",
            payload={
                "name": "words",
                "stereotype": "NONE",
                "parent": None,
                "metadata": {"language": "en"},
            },
        )
        store = replay(log)
        t = store.get_tier("words")
        assert t is not None
        assert t.stereotype == TierStereotype.NONE
        assert t.metadata == {"language": "en"}

    def test_replay_add_then_remove_annotation(self):
        from lacing.model import Annotation, MediaRef, Provenance
        from lacing.time import RationalTime, TimeInterval

        ann_id = uuid4()
        ann = Annotation(
            id=ann_id,
            tier="words",
            reference=MediaRef(
                asset_id="x",
                interval=TimeInterval(RationalTime(0), RationalTime(10)),
            ),
            body={"text": "hi"},
            body_schema_uri="annot://schema/word/v1",
            provenance=Provenance(
                was_generated_by="user:test",
                was_attributed_to="test",
                generated_at_time=RationalTime(0),
            ),
        )

        log = InMemoryOpLog()
        log.append(
            "add_tier",
            target_id="words",
            payload={"name": "words", "stereotype": "NONE", "parent": None, "metadata": {}},
        )
        log.append(
            "add_annotation",
            target_id=str(ann_id),
            payload={"annotation": ann.model_dump(mode="json")},
        )

        # At clock=2: tier + 1 annotation present.
        s2 = replay(log, until_clock=2)
        assert len(list(s2.all())) == 1
        assert next(s2.all()).id == ann_id

        # Now remove and replay further.
        log.append("remove_annotation", target_id=str(ann_id), payload={})
        s3 = replay(log, until_clock=3)
        assert len(list(s3.all())) == 0

    def test_replay_until_intermediate_clock(self):
        log = InMemoryOpLog()
        log.append(
            "add_tier",
            target_id="words",
            payload={"name": "words", "stereotype": "NONE", "parent": None, "metadata": {}},
        )
        log.append(
            "add_tier",
            target_id="phon",
            payload={"name": "phon", "stereotype": "NONE", "parent": None, "metadata": {}},
        )
        # Snapshot at clock=1 has only `words`.
        s = replay(log, until_clock=1)
        assert s.get_tier("words") is not None
        assert s.get_tier("phon") is None

    def test_replay_unknown_op_skipped(self):
        log = InMemoryOpLog()
        log.append("never_heard_of_this_op", target_id="x", payload={})
        store = replay(log)
        assert len(list(store.all())) == 0  # No-op


# ---------------------------------------------------------------------------
# server integration: clock header + /oplog + /state-at
# ---------------------------------------------------------------------------


pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from lacing.server import create_app  # noqa: E402
from lacing.server.deps import get_oplog, get_store  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier  # noqa: E402


@pytest.fixture
def server_setup():
    store = MemoryStore()
    store.add_tier(Tier("words"))
    log = InMemoryOpLog()
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_oplog] = lambda: log
    client = TestClient(app)
    return client, store, log


def _annotation_payload(start_ms: int = 0, end_ms: int = 1000, text: str = "hi") -> dict:
    return {
        "tier": "words",
        "reference": {
            "kind": "media",
            "asset_id": "x",
            "interval": {
                "start": {"v": start_ms, "r": 1000},
                "end": {"v": end_ms, "r": 1000},
            },
        },
        "body": {"text": text},
        "body_schema_uri": "annot://schema/word/v1",
    }


class TestServerIntegration:
    def test_create_records_oplog_entry(self, server_setup):
        client, _store, log = server_setup
        r = client.post("/annotations", json=_annotation_payload())
        assert r.status_code == 201
        assert r.headers.get("X-Lacing-Clock") == "1"
        assert log.latest_clock() == 1
        entry = next(log.entries())
        assert entry.operation == "add_annotation"

    def test_delete_records_oplog_entry(self, server_setup):
        client, _store, log = server_setup
        post = client.post("/annotations", json=_annotation_payload())
        ann_id = post.json()["id"]
        d = client.delete(f"/annotations/{ann_id}")
        assert d.status_code == 204
        assert d.headers.get("X-Lacing-Clock") == "2"
        ops = [e.operation for e in log.entries()]
        assert ops == ["add_annotation", "remove_annotation"]

    def test_patch_records_oplog_entry(self, server_setup):
        client, _store, _log = server_setup
        post = client.post("/annotations", json=_annotation_payload())
        ann_id = post.json()["id"]
        etag = post.headers["ETag"]
        patched = client.patch(
            f"/annotations/{ann_id}",
            headers={"If-Match": etag},
            json={"body": {"text": "updated"}},
        )
        assert patched.status_code == 200
        assert patched.headers.get("X-Lacing-Clock") == "2"

    def test_create_tier_records_oplog_entry(self, server_setup):
        client, _store, log = server_setup
        r = client.post(
            "/tiers",
            json={"name": "phon", "stereotype": "TIME_SUBDIVISION", "parent": "words"},
        )
        assert r.status_code == 201
        assert r.headers.get("X-Lacing-Clock") == "1"
        assert log.latest_clock() == 1


class TestOplogEndpoints:
    def test_latest_clock_starts_at_zero(self, server_setup):
        client, _store, _log = server_setup
        r = client.get("/oplog/latest-clock")
        assert r.status_code == 200
        assert r.json() == {"clock": 0}

    def test_latest_clock_increments_on_writes(self, server_setup):
        client, _store, _log = server_setup
        client.post("/annotations", json=_annotation_payload())
        r = client.get("/oplog/latest-clock")
        assert r.json() == {"clock": 1}

    def test_list_oplog_full(self, server_setup):
        client, _store, _log = server_setup
        client.post("/annotations", json=_annotation_payload(start_ms=0, end_ms=1000))
        client.post("/annotations", json=_annotation_payload(start_ms=2000, end_ms=3000))
        r = client.get("/oplog")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) == 2
        assert all(e["operation"] == "add_annotation" for e in entries)

    def test_list_oplog_clock_range(self, server_setup):
        client, _store, _log = server_setup
        for i in range(4):
            client.post("/annotations", json=_annotation_payload(start_ms=i * 1000, end_ms=(i + 1) * 1000))
        r = client.get("/oplog", params={"from_clock": 2, "until_clock": 3})
        clocks = [e["clock"] for e in r.json()]
        assert clocks == [2, 3]


class TestStateAt:
    def test_state_at_zero_is_empty(self, server_setup):
        client, _store, _log = server_setup
        client.post("/annotations", json=_annotation_payload())
        r = client.get("/state-at", params={"clock": 0})
        assert r.status_code == 200
        body = r.json()
        assert body["at_clock"] == 0
        assert body["annotations"] == []
        assert body["tiers"] == []

    def test_state_at_intermediate_clock(self, server_setup):
        client, _store, _log = server_setup
        # 1: add_tier `phon`
        client.post("/tiers", json={"name": "phon"})
        # 2: add an annotation
        client.post("/annotations", json=_annotation_payload(text="first"))
        # 3: add another
        post3 = client.post("/annotations", json=_annotation_payload(start_ms=1000, end_ms=2000, text="second"))
        ann_id_2 = post3.json()["id"]
        # 4: delete the second
        client.delete(f"/annotations/{ann_id_2}")

        # At clock=3, both annotations exist.
        r3 = client.get("/state-at", params={"clock": 3})
        assert r3.status_code == 200
        anns_at_3 = r3.json()["annotations"]
        texts_at_3 = sorted(a["body"]["text"] for a in anns_at_3)
        assert texts_at_3 == ["first", "second"]

        # At clock=4, the second is gone.
        r4 = client.get("/state-at", params={"clock": 4})
        anns_at_4 = r4.json()["annotations"]
        texts_at_4 = [a["body"]["text"] for a in anns_at_4]
        assert texts_at_4 == ["first"]

    def test_state_at_too_high_clock_400(self, server_setup):
        client, _store, _log = server_setup
        r = client.get("/state-at", params={"clock": 999})
        assert r.status_code == 400

    def test_state_at_includes_tiers(self, server_setup):
        client, _store, _log = server_setup
        client.post("/tiers", json={"name": "phon", "stereotype": "TIME_SUBDIVISION", "parent": "words"})
        r = client.get("/state-at", params={"clock": 1})
        body = r.json()
        names = {t["name"] for t in body["tiers"]}
        assert "phon" in names
