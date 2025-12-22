def render_circuit_answer(circuit: dict) -> str:
    """Format a circuit dictionary into a user-friendly answer string."""
    name = circuit.get("name", "Unknown Circuit")
    ic = circuit.get("ic", "N/A")
    specs = circuit.get("specifications", {}) or {}
    
    lines = []
    lines.append(f"Mạch phù hợp: {name} (IC: {ic}).")
    lines.append("")
    lines.append("Nguyên lý:")
    lines.append("- Mạch mẫu Phase 1 để học và triển khai nhanh.")
    lines.append("")
    lines.append("**Thông số (từ database)**:")
    
    def dump(obj, prefix=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                dump(value, prefix + key + ".")
        else:
            lines.append(f"- {prefix[:-1]}: {obj}")
            
    dump(specs)
    lines.append("")
    lines.append("**BOM (gợi ý)**:")
    lines.append("- IC/module chính theo loại mạch.")
    lines.append("- Linh kiện ngoại vi theo schematic mẫu.")
    lines.append("")
    lines.append("**Lưu ý**: Cung cấp Vin/Vout/Iout cụ thể để kiểm tra giới hạn.")

    return "\n".join(lines)

def render_fallback(fallback_text: str) -> str:
    return fallback_text or "❓ Mình chưa hiểu rõ. Thử 'tăng áp', 'giảm áp', 'khuếch đại đảo', 'mạch nhạc' nhé!"