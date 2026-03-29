
path = "app/domains/circuits/ai_core/topology_planner.py"
with open(path, "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
    """        # NÃ¢ng cáº¥p lÃªn multi_stage náº¿u gain >= 100 cho Táº¤T Cáº¢ cÃ¡c loáº¡i máº¡ch\n        if spec.circuit_type != "multi_stage" and spec.gain is not None and spec.gain >= 100:""",
    """        # NÃ¢ng cáº¥p lÃªn multi_stage náº¿u gain >= 100 cho Táº¤T Cáº¢ cÃ¡c loáº¡i máº¡ch\n        # Ngoại trừ inverting, non_inverting, differential, vv. (nhóm op-amp)\n        is_opamp = spec.circuit_type in {\"inverting\", \"non_inverting\", \"differential\", \"instrumentation\"}\n        if not is_opamp and spec.circuit_type != \"multi_stage\" and spec.gain is not None and spec.gain >= 100:"""
)

# Also fix the weird encoding by reading text and manually applying the patch based on line numbers or explicit replace

