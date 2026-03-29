import os

file_path = "app/domains/circuits/ai_core/circuit_generator.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the mapping logic to handle VOLTAGE_SOURCE/voltage
old_logic = """                elif comp_type == "INDUCTOR" or "inductance" in params:
                    params["inductance"] = val
                    applied.append(f"{comp_id}.inductance = {val}")"""

new_logic = """                elif comp_type == "INDUCTOR" or "inductance" in params:
                    params["inductance"] = val
                    applied.append(f"{comp_id}.inductance = {val}")

                elif comp_type == "VOLTAGE_SOURCE" or "voltage" in params:
                    params["voltage"] = val
                    applied.append(f"{comp_id}.voltage = {val}")"""

if old_logic in content:
    content = content.replace(old_logic, new_logic)
    
old_map_logic = """                    if comp_type == "RESISTOR" or "resistance" in params:       
                        params["resistance"] = val
                        applied.append(f"{comp_id}.resistance = {val} (mapped from {key})")"""

new_map_logic = """                    if comp_type == "RESISTOR" or "resistance" in params:       
                        params["resistance"] = val
                        applied.append(f"{comp_id}.resistance = {val} (mapped from {key})")
                    elif comp_type == "CAPACITOR" or "capacitance" in params:
                        params["capacitance"] = val
                        applied.append(f"{comp_id}.capacitance = {val} (mapped from {key})")
                    elif comp_type == "INDUCTOR" or "inductance" in params:
                        params["inductance"] = val
                        applied.append(f"{comp_id}.inductance = {val} (mapped from {key})")
                    elif comp_type == "VOLTAGE_SOURCE" or "voltage" in params:
                        params["voltage"] = val
                        applied.append(f"{comp_id}.voltage = {val} (mapped from {key})")"""
                        
if old_map_logic in content:
    content = content.replace(old_map_logic, new_map_logic)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("CircuitGenerator updated")

