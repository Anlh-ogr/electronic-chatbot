import json
import glob
import os

templates_dir = "resources/templates"
for root, _, files in os.walk(templates_dir):
    for file in files:
        if file.endswith(".json"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    for comp in data.get("components", []):
                        if str(comp.get("type")).upper() == "VOLTAGE_SOURCE":
                            print(f"{path} -> id: {comp.get('id')} voltage: {comp.get('parameters', {}).get('voltage')}")
                except Exception:
                    pass

