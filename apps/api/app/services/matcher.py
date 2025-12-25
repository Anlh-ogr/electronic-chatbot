# Hiểu cách hệ thống "Suy Nghĩ" hoạt động để tìm mạch phù hợp dựa trên từ khóa trong yêu cầu của người dùng.
""" Phân tích câu     | Chuẩn hóa input
    So khớp keywords  | Chấm điểm score
    Ưu tiên loại mạch | Không liên quan HTTP, Json, Frontend """


import re                          # Xử lý chuỗi nâng cao > in/split/replace -> user nhập tự do
from typing import Dict, Any       # Dict, Any -> dùng cho type hinting, không ảnh hưởng runtime -> IDE auto-complete | test + review thesis | code dễ


# Chuẩn hóa input text
def normalize (text: str) -> str:
    """ lowercase + loai bo khoang trang thua  """
    text = text.lower()
    # Chuẩn hóa khoảng trắng thừa
    text = re.sub(r"\s+", " ", text.strip())
    return text

# Hàm tìm kiếm mạch phù hợp trong danh sách circuits dựa trên message và thứ tự ưu tiên
def match_circuit(message: str, circuits: list, priority_order: list) -> Dict[str, Any]:
    """ Keyword-based match.
        - Score = number of matched keywords.
        - Tie-break by category priority_order (power > analog > oscillator). file.json[8-12]"""
    msg = normalize(message)

    hits = []                   # Lưu trữ các mạch phù hợp
    for circ in circuits:
        score = 0               # Đếm số key khớp
        match_keys = []         # Lưu trữ các key đã khớp

        # Kiểm tra từng key trong mạch
        for keyword in circ.get("keywords", []):
            key = normalize(keyword)
            if key and key in msg:
                score += 1
                match_keys.append(keyword)

        # Nếu key khớp, add vào danh sách hits -> [circuit, score, matched_keywords]
        if score > 0:
            hits.append({
                "circuit": circ,
                "score": score,
                "matched_keywords": match_keys
            })

    # Nếu không có mạch nào khớp -> trả về không khớp [matched: False]
    if not hits:
        return {"matched": False}

    # Sắp xếp: ưu tiên loại mạch (thấp hơn = ưu tiên cao hơn), sau đó là điểm số (cao hơn = ưu tiên cao hơn)
    priority = {cat: idx for idx, cat in enumerate(priority_order or [])}
    hits.sort(key=lambda hit: (priority.get(hit["circuit"].get("category"), 999), -hit["score"]))
    
    
    top_hit = hits[0]
    # Trả về mạch phù hợp nhất với cấu trúc nhất quán
    return {
    "matched": True,
    "circuit": top_hit["circuit"],
    "debug": {
        "score": top_hit["score"],
        "matched_keywords": top_hit["matched_keywords"],
        "candidates": len(hits),
    },
}
