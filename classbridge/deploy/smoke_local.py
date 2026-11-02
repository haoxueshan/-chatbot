"""Exercise a running private demo deployment, never a paid provider.

Uses CLASSBRIDGE_TEST_PASSWORD or the ignored .local/credentials.txt created for
this development checkout. Creates explicitly labelled demo fixtures; does not
delete user sessions. Run from project root with .venv/Scripts/python.exe.
"""
import argparse
import asyncio
import io
import json
import os
import time
from pathlib import Path

import httpx
from docx import Document
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]


async def smoke(base):
    password = os.environ.get("CLASSBRIDGE_TEST_PASSWORD")
    if not password:
        credential = ROOT / ".local/credentials.txt"
        password = next(line.split(": ", 1)[1] for line in credential.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Password: "))
    results = []

    def check(name, condition):
        assert condition, name
        results.append({"check": name, "passed": True})
        print("PASS", name)

    async with httpx.AsyncClient(base_url=base, headers={"Origin": base}, timeout=35, trust_env=False) as client:
        check("health", (await client.get("/api/health")).status_code == 200)
        check("private sessions require login", (await client.get("/api/sessions")).status_code == 401)
        login = await client.post("/api/auth/login", json={"username": "admin", "password": password})
        check("administrator login", login.status_code == 200)
        settings = (await client.get("/api/settings")).json()
        if not settings["api_key_configured"]:
            blocked = await client.post("/api/sessions", json={"title": "不得产生模拟字幕", "mode": "real"})
            check("real mode explicitly rejects missing key", blocked.status_code == 503 and blocked.json()["detail"]["code"] == "missing_api_key")
        response = await client.post("/api/sessions", json={"title": "验收 · 韩英双语 RAG 课堂", "kind": "classroom", "mode": "demo", "retain_audio": False})
        check("create labelled demo session", response.status_code == 201)
        session_id = response.json()["id"]
        cookie = "; ".join(f"{key}={value}" for key, value in client.cookies.items())
        ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
        events = []
        async with connect(f"{ws_base}/ws/sessions/{session_id}?after_seq=0", additional_headers={"Cookie": cookie}, origin=base, proxy=None) as ws:
            await ws.send(json.dumps({"type": "start"}))
            stopped = False
            final_ids = set()
            for _ in range(200):
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                events.append(event)
                if event["type"] == "translation.final":
                    final_ids.add(event["sentence_id"])
                if len(final_ids) >= 3 and not stopped:
                    await ws.send(json.dumps({"type": "stop"}))
                    stopped = True
                if stopped and event["type"] == "session.state" and event.get("state") == "stopped":
                    break
        check("streaming partial and stable bilingual events", all(any(e["type"] == kind for e in events) for kind in ("transcript.partial", "transcript.final", "translation.partial", "translation.final")))
        durable = [e["event_seq"] for e in events if e.get("event_seq")]
        check("durable events strictly ordered", durable == sorted(set(durable)))
        check("demo events never claim real mode", all(e.get("mode") == "demo" for e in events))
        detail = (await client.get(f"/api/sessions/{session_id}")).json()
        check("stop persists captions", detail["status"] == "stopped" and len(detail["segments"]) >= 3)
        count = len(detail["segments"])
        await asyncio.sleep(1)
        check("stop halts new captions", len((await client.get(f"/api/sessions/{session_id}")).json()["segments"]) == count)
        cursor = durable[-2]
        async with connect(f"{ws_base}/ws/sessions/{session_id}?after_seq={cursor}", additional_headers={"Cookie": cookie}, origin=base, proxy=None) as ws:
            recovered = []
            for _ in range(10):
                event = json.loads(await asyncio.wait_for(ws.recv(), 5))
                if event.get("event_seq", 0) > cursor:
                    recovered.append(event)
                    break
            check("reconnect replays without opening microphone", bool(recovered))
        search = (await client.get("/api/sessions", params={"q": "RAG"})).json()
        check("search saved original text", any(s["id"] == session_id for s in search))
        doc = Document()
        doc.add_heading("RAG 课堂讲义（自动验收样本）", 0)
        doc.add_paragraph("检索增强生成 RAG 将外部资料作为回答依据。Hybrid search combines keyword matching and semantic similarity. Evidence must include an original sentence or document location.")
        doc.add_paragraph("向量检索关注语义相似度；关键词检索关注词语匹配。课堂问答应保留来源版本，证据不足时明确说明。")
        blob = io.BytesIO(); doc.save(blob)
        upload = await client.post("/api/documents", data={"session_id": session_id, "mode": "demo"}, files={"file": ("RAG课堂讲义.docx", blob.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        check("DOCX upload accepted", upload.status_code == 201)
        document_id = upload.json()["id"]
        for _ in range(40):
            document = (await client.get(f"/api/documents/{document_id}")).json()
            if document["status"] in ("ready", "failed"):
                break
            await asyncio.sleep(.5)
        check("document parsed and indexed with source location", document["status"] == "ready" and bool(document["chunks"]))
        answer = await client.post("/api/chat", json={"session_id": session_id, "scope": "session", "question": "RAG 和向量检索是什么？", "mode": "demo", "document_ids": []})
        check("RAG answers with validated citations", answer.status_code == 200 and bool(answer.json()["citations"]))
        for citation in answer.json()["citations"]:
            if citation["kind"] == "sentence":
                versions = (await client.get(f"/api/sessions/{citation['session_id']}/versions/{citation['sentence_id']}")).json()
                check("citation resolves to exact text and revision", any(v["source_revision"] == citation["source_revision"] and v["text"] == citation["quote"] for v in versions))
            else:
                source = (await client.get(f"/api/documents/{citation['document_id']}")).json()
                check("document citation resolves to original chunk", any(c["text"] == citation["quote"] for c in source["chunks"]))
        await client.post(f"/api/sessions/{session_id}/summarize")
        for _ in range(40):
            detail = (await client.get(f"/api/sessions/{session_id}")).json()
            if detail["stages"]:
                break
            await asyncio.sleep(.5)
        check("background summary bound to source versions", bool(detail["stages"]) and bool(detail["stages"][0]["sources"]))
        output = ROOT / "test-results"
        output.mkdir(exist_ok=True)
        for format in ("md", "txt", "pdf"):
            exported = await client.get(f"/api/sessions/{session_id}/export", params={"format": format})
            check(f"{format} export", exported.status_code == 200 and len(exported.content) > 100)
            (output / f"demo-export.{format}").write_bytes(exported.content)
        result = {"time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "base_url": base, "session_id": session_id, "document_id": document_id, "checks": results, "paid_api_calls": 0, "note": "Local HTTP/WebSocket integration test; no real microphone or cloud inference."}
        (output / "smoke.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"SUCCESS: {len(results)} checks; session_id={session_id}; paid API calls=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    asyncio.run(smoke(parser.parse_args().base.rstrip("/")))
