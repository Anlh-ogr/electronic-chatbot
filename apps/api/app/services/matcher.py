# matcher nhan dang loai mach tu request text
import re           # match các keyword trong request text
from typing import List, Dict, Any


# Chuan hoa input text -> lowercase + loai bo khoang trang thua 
def normalize (text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text.strip())   # chuan hoa khoang trang giua cac tu
    return text

# Ham tim kiem mach phu hop trong danh sach circuits dua tren message va thu tu uu tien
def match_circuit(message: str, circuits: list, priority_order: list) -> Dict[str, Any]:
    msg = normalize(message)
    
    hits = []                   # luu tru cac mach(kha phu hop) duoc tim thay
    for circ in circuits:
        score = 0               # dem keyword
        match_keys = []            # luu tru keyword duoc tim thay
        
        # Kiem tra tung keyword trong circuit
        for keyword in circ.get("keywords", []):
            key = normalize(keyword)
            if key and key in msg:
                score += 1
                match_keys.append(keyword)
            
            # Tang diem neu tim thay keyword trong message
            if score > 0:
                hits.append({ "circuit": circ,
                              "score": score,
                              "matched_keywords": match_keys })
    
    # Neu khong co mach nao duoc tim thay -> tra ve match_keys = False
    if not hits:
        return {"match_keys": False}

    # Sap xep hits theo score giam dan + theo thu tu uu tien priority_order: power > analog > oscillator
    priority = { cat: idx for idx, cat in enumerate(priority_order or []) }
    hits.sort(key = lambda hit : (priority.get(hit["circuit"].get("category"), 999), -hit["score"]))
    top_hit = hits[0]
    
    # Tra ve mach co diem cao nhat -> gui ve thong tin mach + diem + keyword duoc tim thay
    return { "circuit": top_hit["circuit"],
             "score": top_hit["score"],
             "match_keys": top_hit["matched_keywords"] }
