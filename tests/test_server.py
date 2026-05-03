"""Tests for the FastAPI server.

Uses FastAPI's ``TestClient`` (httpx under the hood). Each test gets a
fresh in-memory ``MemoryStore`` via ``app.dependency_overrides``.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from lacing.adapters import webvtt as _webvtt_adapter  # noqa: E402, F401  registers
from lacing.model import Annotation, MediaRef, Provenance  # noqa: E402
from lacing.server import create_app  # noqa: E402
from lacing.server.deps import get_store  # noqa: E402
from lacing.store import MemoryStore  # noqa: E402
from lacing.tier import Tier, TierStereotype  # noqa: E402
from lacing.time import RationalTime, TimeInterval  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> MemoryStore:
    """Fresh per-test in-memory store."""
    s = MemoryStore()
    s.add_tier(Tier("words"))
    return s


@pytest.fixture
def client(store) -> TestClient:
    """TestClient with the active store overridden to the per-test fixture."""
    app = create_app()
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def _annotation_payload(
    *,
    tier: str = "words",
    start_ms: int = 0,
    end_ms: int = 1000,
    text: str = "hello",
) -> dict:
    return {
        "tier": tier,
        "reference": {
            "kind": "media",
            "asset_id": "blake3:test",
            "interval": {
                "start": {"v": start_ms, "r": 1000},
                "end": {"v": end_ms, "r": 1000},
            },
        },
        "body": {"text": text},
        "body_schema_uri": "annot://schema/word/v1",
    }


# ---------------------------------------------------------------------------
# health + meta
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# tiers
# ---------------------------------------------------------------------------


class TestTiers:
    def test_create(self, client):
        r = client.post(
            "/tiers",
            json={"name": "phonemes", "stereotype": "TIME_SUBDIVISION", "parent": "words"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "phonemes"
        assert body["stereotype"] == "TIME_SUBDIVISION"
        assert body["parent"] == "words"

    def test_list(self, client):
        r = client.get("/tiers")
        assert r.status_code == 200
        names = {t["name"] for t in r.json()}
        assert "words" in names

    def test_get_existing(self, client):
        r = client.get("/tiers/words")
        assert r.status_code == 200
        assert r.json()["name"] == "words"

    def test_get_missing(self, client):
        r = client.get("/tiers/never")
        assert r.status_code == 404

    def test_invalid_stereotype_rejected(self, client):
        r = client.post(
            "/tiers",
            json={"name": "x", "stereotype": "NOT_A_REAL_STEREOTYPE"},
        )
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# annotations CRUD
# ---------------------------------------------------------------------------


class TestAnnotations:
    def test_create_returns_etag(self, client):
        r = client.post("/annotations", json=_annotation_payload())
        assert r.status_code == 201
        assert "ETag" in r.headers
        body = r.json()
        assert body["tier"] == "words"
        assert "id" in body
        assert body["provenance"]["was_generated_by"] == "server:lacing"

    def test_get_returns_etag(self, client):
        post = client.post("/annotations", json=_annotation_payload())
        ann_id = post.json()["id"]

        get = client.get(f"/annotations/{ann_id}")
        assert get.status_code == 200
        assert "ETag" in get.headers
        assert get.headers["ETag"] == post.headers["ETag"]
        assert get.json()["id"] == ann_id

    def test_get_missing_404(self, client):
        r = client.get(f"/annotations/{uuid4()}")
        assert r.status_code == 404

    def test_delete(self, client):
        post = client.post("/annotations", json=_annotation_payload())
        ann_id = post.json()["id"]
        d = client.delete(f"/annotations/{ann_id}")
        assert d.status_code == 204
        # Idempotent? 404 on second delete.
        d2 = client.delete(f"/annotations/{ann_id}")
        assert d2.status_code == 404

    def test_invalid_reference_kind(self, client):
        bad = _annotation_payload()
        bad["reference"] = {"kind": "lol", "asset_id": "x"}
        r = client.post("/annotations", json=bad)
        assert r.status_code == 400

    def test_explicit_id_preserved(self, client):
        my_id = str(uuid4())
        payload = _annotation_payload()
        payload["id"] = my_id
        r = client.post("/annotations", json=payload)
        assert r.status_code == 201
        assert r.json()["id"] == my_id


# ---------------------------------------------------------------------------
# annotations list / filter
# ---------------------------------------------------------------------------


class TestAnnotationList:
    def _seed(self, client) -> None:
        # Three annotations: 0-1s, 1-2s, 5-6s on tier 'words'.
        for s, e in [(0, 1000), (1000, 2000), (5000, 6000)]:
            client.post("/annotations", json=_annotation_payload(start_ms=s, end_ms=e))

    def test_list_all(self, client):
        self._seed(client)
        r = client.get("/annotations")
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_list_window_intersects(self, client):
        self._seed(client)
        r = client.get(
            "/annotations",
            params={
                "start": 0.5,
                "end": 1.5,
                "rate": 1000,
                "relation": "intersects",
            },
        )
        assert r.status_code == 200
        # [0, 1) and [1, 2) both intersect [0.5, 1.5)
        assert len(r.json()) == 2

    def test_list_window_during(self, client):
        self._seed(client)
        r = client.get(
            "/annotations",
            params={
                "start": -1,
                "end": 1.5,
                "rate": 1000,
                "relation": "during",
            },
        )
        assert r.status_code == 200
        # Only [0, 1) is strictly during [-1, 1.5)
        assert len(r.json()) == 1

    def test_list_partial_window_400(self, client):
        r = client.get("/annotations", params={"start": 0.5})
        assert r.status_code == 400

    def test_list_filter_by_tier(self, client):
        client.post("/annotations", json=_annotation_payload(tier="words"))
        # Pre-create a second tier, then add to it.
        client.post("/tiers", json={"name": "phonemes"})
        client.post(
            "/annotations", json=_annotation_payload(tier="phonemes", text="ph")
        )

        r = client.get("/annotations", params={"tier": "phonemes"})
        assert r.status_code == 200
        assert all(a["tier"] == "phonemes" for a in r.json())
        assert len(r.json()) == 1

    def test_list_unknown_relation_400(self, client):
        self._seed(client)
        r = client.get(
            "/annotations",
            params={"start": 0, "end": 10, "rate": 1000, "relation": "bogus"},
        )
        assert r.status_code == 400

    def test_list_limit(self, client):
        self._seed(client)
        r = client.get("/annotations", params={"limit": 2})
        assert r.status_code == 200
        assert len(r.json()) == 2


# ---------------------------------------------------------------------------
# PATCH with ETag
# ---------------------------------------------------------------------------


class TestPatchETag:
    def _create(self, client) -> tuple[str, str]:
        r = client.post("/annotations", json=_annotation_payload())
        return r.json()["id"], r.headers["ETag"]

    def test_patch_with_correct_etag(self, client):
        ann_id, etag = self._create(client)
        r = client.patch(
            f"/annotations/{ann_id}",
            headers={"If-Match": etag},
            json={"body": {"text": "updated"}},
        )
        assert r.status_code == 200
        assert r.json()["body"]["text"] == "updated"
        assert r.headers["ETag"] != etag  # new content -> new ETag

    def test_patch_with_wildcard_etag(self, client):
        ann_id, _etag = self._create(client)
        r = client.patch(
            f"/annotations/{ann_id}",
            headers={"If-Match": "*"},
            json={"confidence": 0.5},
        )
        assert r.status_code == 200
        assert r.json()["confidence"] == 0.5

    def test_patch_without_if_match_428(self, client):
        ann_id, _ = self._create(client)
        r = client.patch(
            f"/annotations/{ann_id}",
            json={"body": {"text": "x"}},
        )
        assert r.status_code == 428  # Precondition Required

    def test_patch_with_stale_etag_412(self, client):
        ann_id, _ = self._create(client)
        r = client.patch(
            f"/annotations/{ann_id}",
            headers={"If-Match": '"deadbeef"'},
            json={"body": {"text": "x"}},
        )
        assert r.status_code == 412

    def test_patch_with_malformed_etag_400(self, client):
        ann_id, _ = self._create(client)
        r = client.patch(
            f"/annotations/{ann_id}",
            headers={"If-Match": "no-quotes"},
            json={"body": {"text": "x"}},
        )
        assert r.status_code == 400

    def test_patch_missing_annotation_404(self, client):
        r = client.patch(
            f"/annotations/{uuid4()}",
            headers={"If-Match": '"x"'},
            json={"body": {"text": "x"}},
        )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# import / export
# ---------------------------------------------------------------------------


SAMPLE_VTT = """WEBVTT

1
00:00:00.000 --> 00:00:01.500
hello

2
00:00:01.500 --> 00:00:03.000
world
"""


class TestImportExport:
    def test_list_formats(self, client):
        r = client.get("/formats")
        assert r.status_code == 200
        names = {fmt["name"] for fmt in r.json()}
        assert "webvtt" in names

    def test_import_webvtt(self, client):
        files = {
            "file": ("sample.vtt", SAMPLE_VTT.encode("utf-8"), "text/vtt"),
        }
        r = client.post(
            "/import",
            params={"format": "webvtt", "rate": 1000},
            files=files,
        )
        assert r.status_code == 201
        body = r.json()
        assert body["format"] == "webvtt"
        assert body["annotations_added"] == 2

        # And the store now has them.
        ann_list = client.get("/annotations").json()
        assert len(ann_list) == 2

    def test_import_unknown_format_400(self, client):
        files = {"file": ("x.bin", b"hi", "application/octet-stream")}
        r = client.post("/import", params={"format": "neverheard"}, files=files)
        assert r.status_code == 400

    def test_export_webvtt(self, client):
        # First create an annotation that uses the WebVTT body shape:
        client.post(
            "/annotations",
            json={
                "tier": "cues",
                "reference": {
                    "kind": "media",
                    "asset_id": "x",
                    "interval": {
                        "start": {"v": 0, "r": 1000},
                        "end": {"v": 1500, "r": 1000},
                    },
                },
                "body": {"text": "hello", "id": None, "settings": {}},
                "body_schema_uri": "annot://schema/webvtt-cue/v1",
            },
        )
        # Need a 'cues' tier to exist.
        client.post("/tiers", json={"name": "cues"})

        r = client.get("/export", params={"format": "webvtt"})
        assert r.status_code == 200
        assert r.content.startswith(b"WEBVTT")
        assert b"hello" in r.content

    def test_export_unknown_format_400(self, client):
        r = client.get("/export", params={"format": "neverheard"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------


class TestSchemas:
    def test_list_schemas(self, client):
        r = client.get("/schemas")
        assert r.status_code == 200
        uris = r.json()
        # Built-in body schemas are registered at app startup.
        assert "annot://schema/word/v1" in uris

    def test_get_schema_for_word_v1(self, client):
        r = client.get("/schemas/annot://schema/word/v1")
        assert r.status_code == 200
        body = r.json()
        assert "properties" in body
        assert "text" in body["properties"]

    def test_get_schema_unknown_404(self, client):
        r = client.get("/schemas/annot://schema/never/v1")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


class TestMeta:
    def test_get_meta_when_unsupported(self, client):
        # MemoryStore has no get_meta — endpoint returns {} not 500.
        r = client.get("/meta")
        assert r.status_code == 200
        assert r.json() == {}

    def test_set_meta_when_unsupported(self, client):
        # MemoryStore has no set_meta — should return 405.
        r = client.put("/meta/foo", json={"value": "bar"})
        assert r.status_code == 405

    def test_meta_with_sqlite_store(self):
        # Wire a SqliteStore in instead — it has get/set_meta. The server
        # runs sync endpoints in a worker thread, so we must allow
        # cross-thread use of the SQLite connection.
        from lacing.server.deps import get_store
        from lacing.store import SqliteStore

        sqlite = SqliteStore(":memory:", check_same_thread=False)
        try:
            app = create_app()
            app.dependency_overrides[get_store] = lambda: sqlite
            client = TestClient(app)

            put = client.put("/meta/project", json={"value": "demo"})
            assert put.status_code == 200
            get = client.get("/meta")
            assert get.status_code == 200
            assert get.json().get("project") == "demo"
            assert "schema_version" in get.json()
        finally:
            sqlite.close()
