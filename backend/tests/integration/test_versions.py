"""Document versions: new-version upload, listing, conflicts, delete promotion, chat scope."""

import uuid

from tests import fixtures
from tests.conftest import run_queued

V1_TEXT = b"Leave policy 2025. Employees receive 25 days of paid annual leave."
V2_TEXT = b"Leave policy 2026. Employees receive 27 days of paid annual leave."


async def _upload(client, name, data):
    r = await client.post("/documents", files=[("files", (name, data, "application/octet-stream"))])
    return r.json()["results"][0]["document"]


async def _new_version(client, doc_id, name, data):
    return await client.post(
        f"/documents/{doc_id}/versions", files={"file": (name, data, "application/octet-stream")}
    )


async def test_new_version_is_latest_and_old_one_is_kept(client, enqueued):
    v1 = await _upload(client, "leave-policy.txt", V1_TEXT)
    assert (v1["version"], v1["is_latest"], v1["version_group_id"]) == (1, True, v1["id"])
    enqueued.clear()

    r = await _new_version(client, v1["id"], "leave-policy-2026.txt", V2_TEXT)
    assert r.status_code == 202, r.text
    v2 = r.json()
    assert v2["version"] == 2 and v2["is_latest"] is True
    assert v2["version_group_id"] == v1["id"] and v2["filename"] == "leave-policy-2026.txt"
    assert enqueued == [("extract", v2["id"])]  # processed like any upload

    old = (await client.get(f"/documents/{v1['id']}")).json()
    assert old["is_latest"] is False and old["version"] == 1

    listed = (await client.get("/documents")).json()
    assert [d["id"] for d in listed["items"]] == [v2["id"]] and listed["total"] == 1
    everything = (await client.get("/documents", params={"all_versions": True})).json()
    assert {d["id"] for d in everything["items"]} == {v1["id"], v2["id"]}

    versions = (await client.get(f"/documents/{v1['id']}/versions")).json()
    assert [d["version"] for d in versions["items"]] == [2, 1]
    assert versions["latest_id"] == v2["id"] and versions["version_group_id"] == v1["id"]

    # Any version id can be the parent: the next number is taken from the whole group.
    r = await _new_version(client, v1["id"], "leave-policy.pdf", fixtures.five_page_pdf())
    assert r.status_code == 202 and r.json()["version"] == 3 and r.json()["file_type"] == "pdf"
    versions = (await client.get(f"/documents/{v2['id']}/versions")).json()
    assert [(d["version"], d["is_latest"]) for d in versions["items"]] == [
        (3, True),
        (2, False),
        (1, False),
    ]


async def test_version_conflicts_and_rejections(client, enqueued):
    v1 = await _upload(client, "leave-policy.txt", V1_TEXT)
    other = await _upload(client, "other.txt", b"A completely different document.")

    same = await _new_version(client, v1["id"], "copy.txt", V1_TEXT)
    assert same.status_code == 409
    assert same.json()["error"]["code"] == "VERSION_UNCHANGED"
    assert same.json()["error"]["details"] == {"document_id": v1["id"], "version": 1}

    dup = await _new_version(client, v1["id"], "x.txt", b"A completely different document.")
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_CONTENT"
    assert dup.json()["error"]["details"]["document_id"] == other["id"]

    binary = await _new_version(client, v1["id"], "v2.pdf", b"MZ\x90\x00binary")
    assert binary.status_code == 415 and binary.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    empty = await _new_version(client, v1["id"], "v2.txt", b"")
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "EMPTY_FILE"

    missing = await _new_version(client, uuid.uuid4(), "v2.txt", V2_TEXT)
    assert missing.status_code == 404
    assert (await client.get(f"/documents/{uuid.uuid4()}/versions")).status_code == 404

    # Nothing above changed the group.
    detail = (await client.get(f"/documents/{v1['id']}")).json()
    assert detail["is_latest"] is True and detail["version"] == 1


async def test_deleting_the_latest_version_promotes_the_previous_one(client, enqueued):
    v1 = await _upload(client, "leave-policy.txt", V1_TEXT)
    v2 = (await _new_version(client, v1["id"], "leave-policy.txt", V2_TEXT)).json()
    v3 = (await _new_version(client, v1["id"], "leave-policy.txt", V2_TEXT + b" Updated.")).json()

    assert (await client.delete(f"/documents/{v2['id']}")).status_code == 204  # old: no change
    assert (await client.get(f"/documents/{v3['id']}")).json()["is_latest"] is True

    assert (await client.delete(f"/documents/{v3['id']}")).status_code == 204
    promoted = (await client.get(f"/documents/{v1['id']}")).json()
    assert promoted["is_latest"] is True
    assert [d["id"] for d in (await client.get("/documents")).json()["items"]] == [v1["id"]]

    # The next number is max(remaining) + 1, so numbers of deleted versions can be reused.
    nxt = (await _new_version(client, v1["id"], "leave-policy.txt", b"Leave policy v4.")).json()
    assert nxt["version"] == 2 and nxt["is_latest"] is True


async def test_vault_chat_uses_latest_version_and_attached_chats_keep_theirs(client, enqueued):
    v1 = await _upload(client, "leave-policy.txt", V1_TEXT)
    run_queued(enqueued)
    attached = await client.post("/chat/sessions", json={"document_ids": [v1["id"]]})
    attached_id = attached.json()["id"]

    v2 = (await _new_version(client, v1["id"], "leave-policy.txt", V2_TEXT)).json()
    run_queued(enqueued)

    vault = (await client.post("/chat/sessions", json={"scope_mode": "all"})).json()["id"]
    r = await client.post(
        f"/chat/sessions/{vault}/messages", json={"content": "How many days of annual leave?"}
    )
    assert r.status_code == 200, r.text
    answer = r.json()["assistant_message"]
    assert answer["scope_document_ids"] == [v2["id"]]
    assert {c["document_id"] for c in answer["citations"]} == {v2["id"]}

    session = (await client.get(f"/chat/sessions/{attached_id}")).json()
    [doc] = session["documents"]
    assert doc["id"] == v1["id"] and doc["version"] == 1 and doc["is_latest"] is False
    r = await client.post(
        f"/chat/sessions/{attached_id}/messages", json={"content": "How many days of leave?"}
    )
    assert r.json()["assistant_message"]["scope_document_ids"] == [v1["id"]]
