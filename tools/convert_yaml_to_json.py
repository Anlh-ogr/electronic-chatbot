# tools/convert_yaml_to_json setup database for version 1.0.0

from pathlib import Path as path_lib
import json, re                         # doc file json, match keywords for user's input
import yaml                             # doc file yaml

# Define ROOT directory of the project
ROOT = path_lib(__file__).resolve().parents[1]
print (f"ROOT directory: {ROOT}")

# Load YAML File and define JSON output path
YAML_PATH = ROOT / "docs" / "circuit_scope.yaml"
JSON_PATH = ROOT / "apps" / "api" / "app" / "data" / "circuit_scope.json"

# Normalize list of keywords
def norm_keywords(words):
    out, seen = [], set()
    # Xu ly input keywords an toan. None -> [], chuan 
    for write in words or []:
        write = re.sub(r"\s+", " ", str(write).strip())
        
        
        # Skip empty or whitespace-only strings after normalization
        if not write:
            continue
        
        # Convert the string to lowercase for case-insensitive comparison
        keywords = write.lower()
        
        # Skip duplicate keywords that have already been processed
        if keywords in seen:
            continue
        
        # Add the keyword to the set of seen keywords and the output list
        seen.add(keywords)
        out.append(write)
    return out


def main():
    raw = yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))

    circuits = []
    for cat_id, cat in (raw.get("categories") or {}).items():
        for circ in (cat.get("circuits") or []):
            circuits.append({ "id" : circ.get("id"),
                              "category" : cat_id,
                              "name" : circ.get("name"),
                              "ic" : circ.get("ic"),
                              "keywords" : norm_keywords(circ.get("keywords")),
                              "specs" : circ.get("specs") or {} })
    
    db = { "project": raw.get("project") or {},
           "priority_order": (raw.get("rule_engine") or {}).get("priority_order") or [],
           "keyword_match_mode": (raw.get("rule_engine") or {}).get("keyword_match_mode") or "case_insensitive",
           "fallback_response": (raw.get("rule_engine") or {}).get("fallback_response") or "",
           "out_of_scope": raw.get("out_of_scope") or {},
           "circuits": circuits }
    
    JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {JSON_PATH} ({len(circuits)} circuits)")
    
if __name__ == "__main__":
    main()
