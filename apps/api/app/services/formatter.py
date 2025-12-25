# Tầng diễn đạt, định dạng câu trả lời cho user cuối.
""" Không xử lí logic mà chỉ đưa ra câu trả lời cho con người hiểu. """


""" Nhận 1 mạch điện đã được chọn
    Trả về 1 chuỗi text hoàn chỉnh để gửi cho user """
def render_circuit_answer(circuit: dict) -> str:
    """ Render response from circuit + knowledge. 
    uses knowledge fields : principle_md, formulas, bom, notes, images, simulation, eda. [circuit_scope.json] """
    
    name = circuit.get("name", "N/A")
    ic = circuit.get("ic", "N/A")
    specs = circuit.get("specs", {}) or {}
    knowledge = circuit.get("knowledge", {}) or {}
    
    lines: list[str] = []
    lines.append(f"Mạch phù hợp: {name} (IC: {ic})")
    lines.append("")
    
    """ 1. Principle - Nguyên Lý """
    lines.append("Nguyên Lý:")
    lines.append(knowledge.get("principle_md", "Mạch mẫu (chưa có mô tả chi tiết)."))
    lines.append("")
    
    """ 2. BOM - Bill of Materials """
    lines.append("BOM (linh kiện):")
    bom = knowledge.get("bom", []) or []
    
    if bom:
        for item in bom:
            ref = item.get("ref", "N/A")
            value = item.get("value", "N/A")
            footprint = item.get("footprint", "N/A")
            note = item.get("note", "")
            lines.append(f"- {ref}: {value} ({footprint}) {('- ' + note) if note else ''}".rstrip())
    else:
        lines.append("- (Chưa có BOM)")
    
    lines.append("")
        
    
    """ 3. Formulas - Giới hạn để đễ đọc """
    lines.append("Công Thức (một số công thức chính):")
    formulas = knowledge.get("formulas", []) or []
    
    if formulas:
        # Limit to first 6 formulas
        for formula in formulas[:6]:
            lines.append(f"- {formula.get('name','')}: {formula.get('expr','')} {formula.get('note','')}".rstrip())
            if len(formulas) > 6:
                lines.append(f"... và {len(formulas) - 6} công thức khác.")
    else:
        lines.append("Sẽ bổ sung sau.")
    
    lines.append("")
    
    """ 4. Notes - Ghi Chú """
    notes = knowledge.get("notes", []) or knowledge.get("note", []) or []
    
    if notes:
        lines.append("Ghi Chú / Lưu Ý:")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")
    
    """ 5. Specs - Thông Số Kỹ Thuật """
    lines.append("Thông Số Kỹ Thuật (Specs):")
    def dump_specs(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                dump_specs(value, prefix + key + ".")
        else:
            lines.append(f"- {prefix[:-1]}: {obj}")
    
    dump_specs(specs)
            

    """ 6. Images - Hình Ảnh Mạch """
    images = knowledge.get("images", []) or []
    
    if images:
        lines.append("")
        lines.append("Hình Ảnh Tham Khảo:")
        for img in images:
            caption = img.get("caption", "Image")
            url = img.get("url", "")
            lines.append(f"- {caption}: {url}")
    
    return "\n".join(lines)

def render_fallback(text: str) -> str:
    return text or "Mình chưa hiểu rõ. Hãy thử từ khóa: 'tăng áp', 'giảm áp', 'khuếch đại đảo', 'mạch nhạc'."