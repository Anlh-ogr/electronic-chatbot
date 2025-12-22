# matcher nhan dang loai mach tu request text
import re           # match các keyword trong request text
from typing import List, Dict, Any, Optional


# Chuan hoa input text -> lowercase + loai bo khoang trang thua 
def normalize (text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text.strip())   # chuan hoa khoang trang giua cac tu
    return text

# Ham tim kiem mach phu hop trong danh sach circuits dua tren message va thu tu uu tien
def match_circuit(message: str, circuits: list, priority_order: list) -> Dict[str, Any]:
    msg = normalize(message)

    hits = []  # Store potential matching circuits
    for circ in circuits:
        score = 0  # Count matching keywords
        match_keys = []  # Store matched keywords

        # Check each keyword in the circuit
        for keyword in circ.get("keywords", []):
            key = normalize(keyword)
            if key and key in msg:
                score += 1
                match_keys.append(keyword)

        # Add to hits if any keyword matches
        if score > 0:
            hits.append({
                "circuit": circ,
                "score": score,
                "matched_keywords": match_keys
            })

    # If no circuits are found, return consistent structure
    if not hits:
        return {
            "matched": False,
            "circuit": None,
            "debug": {
                "matched_keywords": [],
                "message": msg
            }
        }

    # Sort hits by score descending and priority order
    priority = {cat: idx for idx, cat in enumerate(priority_order or [])}
    hits.sort(key=lambda hit: (priority.get(hit["circuit"].get("category"), 999), -hit["score"]))
    top_hit = hits[0]

    # Return the top matching circuit with consistent structure
    return {
        "matched": True,
        "circuit": top_hit["circuit"],
        "debug": {
            "matched_keywords": top_hit["matched_keywords"],
            "message": msg
        }
    }
