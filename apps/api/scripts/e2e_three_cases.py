import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


BASE = os.environ.get("CHATBOT_API_URL", "http://127.0.0.1:8011").rstrip("/")

CASES = [
    {
        "name": "BJT Common Emitter",
        "prompt": "Thiết kế mạch khuếch đại CE nguồn 12V gain 20.",
    },
    {
        "name": "Op-Amp Non-Inverting",
        "prompt": "Thiết kế op-amp không đảo gain 11 dùng LM358.",
    },
    {
        "name": "Op-Amp Differential",
        "prompt": "Thiết kế op-amp khuếch đại vi sai gain 5.",
    },
]


def post_json(path: str, payload: dict, timeout: int = 120):
    url = BASE + path
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return resp.getcode(), json.loads(body)


def post_chat_sse(payload: dict, timeout: int = 240):
    """Call /api/chat and parse SSE events to extract circuit_ready payload."""
    url = BASE + "/api/chat"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        ctype = resp.headers.get("Content-Type", "")
        body = resp.read().decode("utf-8", errors="ignore")

    if "text/event-stream" not in ctype:
        return status, {"raw": body, "content_type": ctype}

    current_event = ""
    circuit_ready = None
    lines = body.splitlines()
    for line in lines:
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            data_text = line.split(":", 1)[1].strip()
            if current_event == "circuit_ready":
                try:
                    circuit_ready = json.loads(data_text)
                except Exception:
                    pass

    return status, (circuit_ready or {"raw_sse": body})


def post_no_body(path: str, timeout: int = 120):
    url = BASE + path
    req = urllib.request.Request(url, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return resp.getcode(), json.loads(body)


def get_json(path: str, timeout: int = 60):
    url = BASE + path
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return resp.getcode(), json.loads(body)


def run_case(case: dict) -> dict:
    name = case["name"]
    prompt = case["prompt"]
    out = {"name": name, "prompt": prompt}
    print(f"\n=== {name} ===")

    # 1) Request -> generate circuit
    try:
        status, chat = post_chat_sse({"message": prompt, "mode": "fast"}, timeout=300)
        out["chat_status"] = status
        out["chat_ok"] = status == 200
        out["chat_keys"] = sorted(list(chat.keys())) if isinstance(chat, dict) else []
    except Exception as e:
        out["chat_ok"] = False
        out["chat_error"] = str(e)
        return out

    circuit_data = chat.get("circuit_data") if isinstance(chat, dict) else None
    circuit_id = chat.get("circuit_id") if isinstance(chat, dict) else None
    out["circuit_id"] = circuit_id
    out["has_circuit_data"] = isinstance(circuit_data, dict)

    if not isinstance(circuit_data, dict):
        out["schematic_ok"] = False
        out["pcb_ok"] = False
        out["simulate_ok"] = False
        out["error"] = "chat response missing circuit_data"
        return out

    # 2) Schematic export
    try:
        payload = {"circuit_data": circuit_data, "circuit_id": circuit_id or name.replace(" ", "_")}
        status, sch = post_json("/api/chat/export-kicad", payload, timeout=180)
        out["schematic_status"] = status
        out["schematic_ok"] = status == 200
        out["schematic_file_id"] = sch.get("file_id")
        out["schematic_url"] = sch.get("url")
    except Exception as e:
        out["schematic_ok"] = False
        out["schematic_error"] = str(e)

    # 3) PCB export strict
    out["pcb_ok"] = False
    if circuit_id:
        try:
            submit_path = f"/api/circuits/export/{circuit_id}/pcb/industrial/submit?routing_mode=strict"
            status, submit = post_no_body(submit_path, timeout=90)
            out["pcb_submit_status"] = status
            out["pcb_job_id"] = submit.get("job_id")
            result_url = submit.get("result_url")
            if status == 202 and result_url:
                # poll job result
                final_payload = None
                for _ in range(80):
                    _, polled = get_json(result_url, timeout=30)
                    final_payload = polled
                    st = str(polled.get("status", "")).lower()
                    if st in {"completed", "failed", "error", "done"}:
                        break
                    time.sleep(1.5)
                out["pcb_result_status"] = final_payload.get("status") if isinstance(final_payload, dict) else None
                out["pcb_ok"] = str(out["pcb_result_status"]).lower() in {"completed", "done", "success"}
                out["pcb_result"] = final_payload
        except Exception as e:
            out["pcb_error"] = str(e)
    else:
        out["pcb_error"] = "missing circuit_id"

    # 4) SPICE simulation
    try:
        status, sim = post_json("/api/chat/simulate", {"circuit_data": circuit_data}, timeout=240)
        out["simulate_status"] = status
        out["simulate_ok"] = bool(sim.get("success")) if isinstance(sim, dict) else False
        out["simulate_keys"] = sorted(list(sim.keys())) if isinstance(sim, dict) else []
    except Exception as e:
        out["simulate_ok"] = False
        out["simulate_error"] = str(e)

    return out


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    results = [run_case(case) for case in CASES]
    print("\n=== SUMMARY ===")
    for r in results:
        print(
            f"- {r['name']}: "
            f"chat={r.get('chat_ok')} "
            f"sch={r.get('schematic_ok')} "
            f"pcb={r.get('pcb_ok')} "
            f"sim={r.get('simulate_ok')}"
        )
        if r.get("chat_error"):
            print(f"  chat_error={r['chat_error']}")
        if r.get("schematic_error"):
            print(f"  schematic_error={r['schematic_error']}")
        if r.get("pcb_error"):
            print(f"  pcb_error={r['pcb_error']}")
        if r.get("simulate_error"):
            print(f"  simulate_error={r['simulate_error']}")
    print("\nJSON_RESULT_START")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print("JSON_RESULT_END")


if __name__ == "__main__":
    main()

