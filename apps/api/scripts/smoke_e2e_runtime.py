import asyncio
import json

import httpx
import websockets

from app.db.database import SessionLocal
from app.infrastructure.repositories.chat_context_repository import ChatHistoryRepository

BASE_HTTP = "http://127.0.0.1:8000"
BASE_WS = "ws://127.0.0.1:8000"


def resolve_chat_id_from_message(message_id: str) -> str:
    db = SessionLocal()
    try:
        repo = ChatHistoryRepository(db)
        msg = repo.get_message(message_id)
        if msg is None:
            return ""
        return str(msg.chat_id or "").strip()
    finally:
        db.close()


async def wait_health(client: httpx.AsyncClient) -> None:
    last_error = None
    for _ in range(30):
        try:
            resp = await client.get(f"{BASE_HTTP}/api/health", timeout=3.0)
            if resp.status_code == 200:
                print(f"[OK] health: {resp.status_code}")
                return
        except Exception as exc:
            last_error = exc
        await asyncio.sleep(0.25)
    raise RuntimeError(f"Health check failed: {last_error}")


async def main() -> int:
    async with httpx.AsyncClient(timeout=60.0) as client:
        await wait_health(client)

        gen_payload = {
            "prompt": "Create a BJT common emitter amplifier with gain 10 and VCC 12V",
            "parameters": {},
            "circuit_name": "Smoke CE",
        }
        gen_resp = await client.post(f"{BASE_HTTP}/api/circuits/generate/from-prompt", json=gen_payload)
        print(f"[INFO] generate/from-prompt status={gen_resp.status_code}")
        try:
            gen_data = gen_resp.json()
        except Exception:
            gen_data = {"raw": gen_resp.text}

        if gen_resp.status_code == 400:
            raise RuntimeError(
                "generate/from-prompt returned 400 in strict smoke mode: "
                f"{gen_data}"
            )

        if gen_resp.status_code != 200 or "circuit_id" not in gen_data:
            print("[WARN] prompt generation unavailable, trying template fallback")
            fallback_templates = [
                "bjt_common_emitter_externally_biased_amplifier",
                "bjt_common_emitter_externally_biased_bypass_amplifier",
                "bjt_common_emitter_degen_unbypass_amplifier",
            ]

            gen_data = None
            for template_id in fallback_templates:
                direct_payload = {
                    "template_id": template_id,
                    "parameters": {
                        "gain": 10,
                        "vcc": 12,
                    },
                    "circuit_name": "Smoke CE",
                }
                direct_resp = await client.post(f"{BASE_HTTP}/api/circuits/generate", json=direct_payload)
                print(f"[INFO] generate(template={template_id}) status={direct_resp.status_code}")
                if direct_resp.status_code == 201:
                    gen_data = direct_resp.json()
                    break

            if gen_data is None:
                raise RuntimeError(f"Generate failed: {gen_resp.json()}")

        circuit_id = str(gen_data["circuit_id"]).strip()
        if not circuit_id:
            raise RuntimeError("Empty circuit_id from generate response")
        print(f"[OK] generated circuit_id={circuit_id}")

        submit_params = {
            "oracle_validate": "false",
            "oracle_strict": "false",
            "objective_profile": "balanced",
            "enable_power_zones": "false",
        }

        submit_url = f"{BASE_HTTP}/api/circuits/export/{circuit_id}/pcb/industrial/submit"
        submit_resp = await client.post(submit_url, params=submit_params)
        print(f"[INFO] submit industrial status={submit_resp.status_code}")
        submit_data = submit_resp.json()
        if submit_resp.status_code != 202:
            raise RuntimeError(f"Submit failed: {submit_data}")

        job_id = submit_data.get("job_id")
        result_url = BASE_HTTP + submit_data["result_url"]
        events_url = BASE_HTTP + submit_data["events_url"]

        print(f"[OK] submitted job_id={job_id}")

        sse_phases = []
        current_event = None
        final_sse_event = None

        async with client.stream("GET", events_url, timeout=120.0) as stream_resp:
            print(f"[INFO] sse connect status={stream_resp.status_code}")
            if stream_resp.status_code != 200:
                raise RuntimeError(f"SSE connect failed: HTTP {stream_resp.status_code}")

            async for line in stream_resp.aiter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                    continue
                if line.startswith("data:"):
                    payload = json.loads(line.split(":", 1)[1].strip())
                    if current_event == "progress":
                        progress = payload.get("progress") or {}
                        phase = progress.get("phase")
                        if phase and (not sse_phases or sse_phases[-1] != phase):
                            sse_phases.append(phase)
                            print(f"[SSE] phase={phase} progress={progress.get('progress')}")
                    elif current_event in {"result", "error"}:
                        final_sse_event = current_event
                        print(f"[SSE] final_event={current_event} status={payload.get('status')}")
                        break

        result_status_code = None
        result_payload = None
        for _ in range(30):
            result_resp = await client.get(result_url)
            result_status_code = result_resp.status_code
            result_payload = result_resp.json()
            if result_status_code in {200, 500}:
                break
            await asyncio.sleep(0.5)

        print(
            f"[INFO] result endpoint status={result_status_code} "
            f"job_status={result_payload.get('status') if isinstance(result_payload, dict) else 'n/a'}"
        )

        chat_payload = {
            "message": "Thiet ke mach CE gain 8 VCC 12V de test edit",
            "mode": "fast",
        }
        chat_resp = await client.post(f"{BASE_HTTP}/api/chat", json=chat_payload)
        print(f"[INFO] chat status={chat_resp.status_code}")
        chat_data = chat_resp.json()
        if chat_resp.status_code != 200:
            raise RuntimeError(f"Chat failed: {chat_data}")

        session_id = (chat_data.get("session_id") or "").strip()
        user_message_id = (chat_data.get("user_message_id") or "").strip()
        if not user_message_id:
            raise RuntimeError(f"Missing user_message_id for edit test: {chat_data}")

        resolved_chat_id = resolve_chat_id_from_message(user_message_id)
        if not session_id and resolved_chat_id:
            print(f"[WARN] session_id missing in chat response, using resolved chat_id: {resolved_chat_id}")
            session_id = resolved_chat_id
        elif resolved_chat_id and resolved_chat_id != session_id:
            print(
                "[WARN] session_id mismatch from chat response, "
                f"using chat_id from DB message mapping: {resolved_chat_id}"
            )
            session_id = resolved_chat_id

        if not session_id:
            raise RuntimeError(
                f"Cannot resolve chat_id for edit test. user_message_id={user_message_id} chat_response={chat_data}"
            )

        edit_payload = {
            "session_id": session_id,
            "content": "Thiet ke mach CE gain 9 VCC 12V (edited by smoke test)",
        }
        edit_resp = await client.patch(
            f"{BASE_HTTP}/api/chat/messages/{user_message_id}",
            json=edit_payload,
        )
        print(f"[INFO] edit message status={edit_resp.status_code}")
        edit_data = edit_resp.json()
        if edit_resp.status_code != 200:
            raise RuntimeError(f"Edit failed: {edit_data}")
        print(f"[OK] edited message_id={edit_data.get('message_id')} status={edit_data.get('status')}")

        submit2_resp = await client.post(submit_url, params=submit_params)
        print(f"[INFO] submit industrial #2 status={submit2_resp.status_code}")
        submit2_data = submit2_resp.json()
        if submit2_resp.status_code != 202:
            raise RuntimeError(f"Submit #2 failed: {submit2_data}")

        ws_events = []
        ws_stream_url = BASE_WS + submit2_data["ws_url"]
        async with websockets.connect(ws_stream_url, ping_interval=None, open_timeout=10, close_timeout=10) as ws:
            for _ in range(240):
                raw = await asyncio.wait_for(ws.recv(), timeout=90)
                event_payload = json.loads(raw)
                event_name = str(event_payload.get("event") or "")
                ws_events.append(event_name)

                data = event_payload.get("data") or {}
                if event_name == "progress":
                    progress = data.get("progress") or {}
                    print(f"[WS] phase={progress.get('phase')} progress={progress.get('progress')}")
                else:
                    print(f"[WS] final_event={event_name} status={data.get('status')}")

                if event_name in {"result", "error"}:
                    break

        if not ws_events:
            raise RuntimeError("No WebSocket events received")

        result2_resp = await client.get(BASE_HTTP + submit2_data["result_url"])
        result2_payload = result2_resp.json()
        print(
            f"[INFO] result #2 status={result2_resp.status_code} "
            f"job_status={result2_payload.get('status') if isinstance(result2_payload, dict) else 'n/a'}"
        )

        print("[PASS] smoke test completed")
        print(
            json.dumps(
                {
                    "job1": {
                        "job_id": job_id,
                        "sse_phases": sse_phases,
                        "sse_final_event": final_sse_event,
                        "result_status_code": result_status_code,
                        "result_job_status": result_payload.get("status") if isinstance(result_payload, dict) else None,
                    },
                    "edit": {
                        "session_id": session_id,
                        "message_id": user_message_id,
                        "status": edit_data.get("status"),
                    },
                    "job2": {
                        "job_id": submit2_data.get("job_id"),
                        "ws_events": ws_events,
                        "result_status_code": result2_resp.status_code,
                        "result_job_status": result2_payload.get("status") if isinstance(result2_payload, dict) else None,
                    },
                },
                ensure_ascii=False,
            )
        )

        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
