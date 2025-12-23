def render_circuit_answer(circuit: dict) -> str:
    """Format a circuit dictionary into a user-friendly answer string."""
    name = circuit.get("name", "N/A")
    ic = circuit.get("ic", "N/A")
    specs = circuit.get("specs", {}) or {}
    knowledge = circuit.get("knowledge", {}) # Read knowledge
    
    lines = [f"Mạch phù hợp: {name} - IC: {ic}", ""]
    
    # 1. Nguyên Lý
    lines.extend(["Nguyên Lý:"])
    principle = knowledge.get("principle_md", "Mạch mẫu Phase 2.")
    lines.append(principle)
    lines.append("")
    
    # 2. BOM
    lines.extend(["Danh Sách Linh Kiện (BOM):"])
    bom = knowledge.get("bom", [])
    if bom:
        for item in bom:
            ref = item.get("ref", "N/A")
            value = item.get("value", "N/A")
            footprint = item.get("footprint", "N/A")
            note = item.get("note", "")
            lines.append(f"-{ref}: {value} ({footprint}) - {note}")
    else:
        lines.append("Không có thông tin BOM.")
    lines.append("")
        
    
    # 3. Formulas
    lines.extend(["Công Thức Tính Toán:"])
    formulas = knowledge.get("formulas", [])
    if formulas:
        for formula in formulas[:6]:        # Limit to first 6 formulas
            lines.append(f"{formula['name']}: `{formula['expr']}` {formula.get('note', '')}")
        if len(formulas) > 6:
            lines.append(f"... và {len(formulas) - 6} công thức khác.")
    else:
        lines.append("Sẽ bổ sung")
    lines.append("")
    
    # 4. Notes
    notes = knowledge.get("notes", [])
    if notes:
        lines.extend(["**Ghi Chú:**"])
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")
    
    # 5. Specs
    lines.extend(["**Thông Số Kỹ Thuật (Specs)**:"])
    def dump_specs(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                dump_specs(value, prefix + key + ".")
        else:
            lines.append(f"- {prefix[:-1]}: {obj}")
    dump_specs(specs)
            

    # 6. Images
    images = knowledge.get("images", [])
    if images:
        lines.append("")
        lines.append("**Hình Ảnh Mạch**:")
        for img in images:
            lines.append(f"[{img.get('caption','Hình ảnh')}]")
            lines.append(f"[{img.get('url','')}]")
    return "\n".join(lines)

def render_fallback(fallback_text: str) -> str:
    return fallback_text or "Mình chưa hiểu rõ. Thử 'tăng áp', 'giảm áp', 'khuếch đại đảo', 'mạch nhạc' nhé!"