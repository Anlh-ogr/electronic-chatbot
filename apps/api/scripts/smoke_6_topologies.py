"""Quick smoke-test for all 6 supported topologies.

Tests: chat → SCH → PCB (strict) → SPICE simulate
Prints a pass/fail table.
"""
import sys, json, time, asyncio, urllib.request, urllib.error
sys.stdout.reconfigure(encoding="utf-8")

API = "http://localhost:8011"

CIRCUITS = [
    ("BJT CE",     "Thiết kế mạch khuếch đại CE nguồn 12V gain 20"),
    ("BJT CB",     "Thiết kế mạch khuếch đại Common Base BJT gain 10"),
    ("BJT CC",     "Thiết kế mạch khuếch đại Common Collector BJT emitter follower"),
    ("OpAmp Inv",  "Thiết kế mạch khuếch đại đảo dùng LM358 gain 10"),
    ("OpAmp NonInv","Thiết kế op-amp không đảo gain 11 dùng LM358"),
    ("OpAmp Diff", "Thiết kế op-amp khuếch đại vi sai gain 5"),
]

def post_json(path, body, timeout=90):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            body = json.loads(raw)
        except Exception:
            body = {"error": raw.decode("utf-8", errors="replace")[:200]}
        return e.code, body
    except Exception as e:
        return 0, {"error": str(e)}

def post_sse(path, body, timeout=90):
    """Post and collect SSE events; return dict of {event_name: payload}."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    events = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            buf = ""
            for raw_line in r:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        events[current_event] = json.loads(line[5:].strip())
                    except Exception:
                        pass
    except Exception as e:
        events["_error"] = str(e)
    return events

def test_circuit(label, prompt):
    result = {"label": label, "chat": False, "sch": False, "pcb": False, "sim": False,
              "circuit_id": None, "errors": []}

    # 1. Chat (allow up to 3 min for LLM + 4 schema-validation retries)
    events = post_sse("/api/chat", {"message": prompt, "mode": "fast"}, timeout=180)
    cr = events.get("circuit_ready") or {}
    if not cr.get("circuit_id"):
        result["errors"].append(f"chat: no circuit_id. events={list(events.keys())}")
        return result
    result["chat"] = True
    result["circuit_id"] = cr["circuit_id"]
    cd = cr.get("circuit_data") or {}

    # 2. SCH
    sch_status, sch_body = post_json("/api/chat/export-kicad",
        {"circuit_data": cd, "circuit_id": cr["circuit_id"]})
    if sch_status == 200 and (sch_body.get("url") or sch_body.get("sch_url")):
        result["sch"] = True
    else:
        result["errors"].append(f"sch: {sch_status} {str(sch_body)[:200]}")

    # 3. PCB (submit + poll WS via HTTP fallback not available; use REST endpoint if exists)
    # Use POST /api/circuits/export/{id}/pcb/industrial/submit
    pcb_status, pcb_body = post_json(
        f"/api/circuits/export/{cr['circuit_id']}/pcb/industrial/submit?routing_mode=strict",
        {})
    if pcb_status in (200, 202):
        result["pcb"] = True
    else:
        result["errors"].append(f"pcb_submit: {pcb_status} {str(pcb_body)[:200]}")

    # 4. SPICE simulate/stream
    sim_payload = {
        "circuit_data": cd,
        "circuit_id": cr["circuit_id"],
        "analysis_type": "transient",
        "tran_step": "100us",
        "tran_stop": "10ms",
        "tran_start": "0",
    }
    sim_events = post_sse("/api/chat/simulate/stream", sim_payload, timeout=60)
    if sim_events.get("result"):
        result["sim"] = True
    elif sim_events.get("error"):
        err = sim_events["error"]
        fp = err.get("failure_phase", "?")
        result["errors"].append(f"sim: {fp} — {str(err.get('message',''))[:120]}")
    else:
        result["errors"].append(f"sim: no result/error event. events={list(sim_events.keys())}")

    return result


def main():
    print("=" * 72)
    print("SMOKE TEST — 6 topologies")
    print("=" * 72)
    results = []
    for label, prompt in CIRCUITS:
        print(f"\n▶  {label}")
        t0 = time.time()
        r = test_circuit(label, prompt)
        elapsed = time.time() - t0
        ok = r["chat"] and r["sch"] and r["sim"]
        status = "✅ PASS" if ok else "⚠️  PARTIAL" if r["chat"] else "❌ FAIL"
        print(f"   {status}  chat={r['chat']} sch={r['sch']} pcb_submit={r['pcb']} sim={r['sim']}  ({elapsed:.1f}s)")
        if r["errors"]:
            for e in r["errors"]:
                print(f"   ! {e}")
        results.append(r)

    print("\n" + "=" * 72)
    n_pass = sum(1 for r in results if r["chat"] and r["sch"] and r["sim"])
    print(f"TOTAL: {n_pass}/{len(results)} fully passing (chat+sch+sim)")
    print("=" * 72)

if __name__ == "__main__":
    main()
