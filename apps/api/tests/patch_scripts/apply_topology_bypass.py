import re
filepath = "app/application/ai/chatbot_service.py"
with open(filepath, "r", encoding="utf-8") as f:
    text = f.read()

# Replace intent.circuit_type strictly mapping for bypass logic
old_code = """        if (intent.circuit_type or "").strip().lower() == "multi_stage":
            # For multi-stage chains, CE-equivalent DC check is for bias sanity only;
            # total gain target is enforced by constraint validator/simulation gate.
            gain_target = None"""
new_code = """        topology_from_circuit = str(circuit_data.get("topology_type") or "").lower()
        if (intent.circuit_type or "").strip().lower() == "multi_stage" or "multi_stage" in (intent.topology or "").lower() or "two_stage" in topology_from_circuit:
            # For multi-stage chains, CE-equivalent DC check is for bias sanity only;
            # total gain target is enforced by constraint validator/simulation gate.
            gain_target = None"""

if old_code in text:
    text = text.replace(old_code, new_code)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)
    print("Patched successfully!")
else:
    print("Could not find the exact string to replace. Here is what exists near gain_target:")
    idx = text.find("gain_target = None")
    print(text[max(0, idx-200):idx+200])

