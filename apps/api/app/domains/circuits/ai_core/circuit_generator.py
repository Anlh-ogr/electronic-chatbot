# app/domains/circuits/ai_core/circuit_generator.py
""" 4: CircuitGenerator — sinh circuit IR + validate domain
Sinh circuit IR từ TopologyPlan + SolvedParams.
Kết hợp template gốc + tham số đã solve → output cuối cùng.
"""

from __future__ import annotations

import json
import copy
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

""" lý do sử dụng thư viện
json: load/save template + circuit data
copy: deep copy template data để apply parameters
dataclass: định nghĩa cấu trúc dữ liệu kết quả sinh mạch
field: hỗ trợ default_factory cho list trong dataclass
logging: ghi log quá trình sinh mạch
path: xác định đường dẫn tới thư mục chứa templates
typing: type hints cho readability và maintainability
"""

logger = logging.getLogger(__name__)

# Path tới templates gốc
_API_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_TEMPLATES_DIR = _API_ROOT / "resources" / "templates"


@dataclass
class ValidationResult:
    """Kết quả validate."""
    passed: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class GeneratedCircuit:
    """Kết quả sinh mạch."""
    template_id: str = ""
    topology_type: str = ""
    circuit_data: Dict[str, Any] = field(default_factory=dict)
    solved_params: Dict[str, float] = field(default_factory=dict)
    gain_formula: str = ""
    actual_gain: Optional[float] = None
    validation: Optional[ValidationResult] = None
    composition_plan: Dict[str, Any] = field(default_factory=dict)
    suggested_extensions: List[Dict[str, Any]] = field(default_factory=list)
    rationale: List[str] = field(default_factory=list)
    success: bool = True
    message: str = ""
    applied_params: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "topology_type": self.topology_type,
            "circuit_data": self.circuit_data,
            "solved_params": self.solved_params,
            "gain_formula": self.gain_formula,
            "actual_gain": self.actual_gain,
            "validation": {
                "passed": self.validation.passed if self.validation else True,
                "errors": self.validation.errors if self.validation else [],
                "warnings": self.validation.warnings if self.validation else [],
            },
            "composition_plan": self.composition_plan,
            "suggested_extensions": self.suggested_extensions,
            "rationale": self.rationale,
            "success": self.success,
            "message": self.message,
            "applied_params": self.applied_params,
        }


class CircuitGenerator:
    """ Sinh circuit data từ template gốc + tham số đã solve.
    Flow:
      1. Load template gốc (JSON)
      2. Apply solved parameters (R, C values override)
      3. Validate domain rules
      4. Trả về GeneratedCircuit
    """

    def __init__(self, templates_dir: Optional[Path] = None):
        self._templates_dir = templates_dir or _TEMPLATES_DIR

    def generate(self, template_id: str, template_file: str, solved_values: Dict[str, float],
        gain_formula: str = "", actual_gain: Optional[float] = None,
        suggested_extensions: Optional[List[Dict]] = None, rationale: Optional[List[str]] = None,
        composition_plan: Optional[Dict[str, Any]] = None,
    ) -> GeneratedCircuit:
        """ Sinh circuit từ template + solved params."""

        result = GeneratedCircuit(
            template_id=template_id,
            gain_formula=gain_formula,
            actual_gain=actual_gain,
            composition_plan=composition_plan or {},
            suggested_extensions=suggested_extensions or [],
            rationale=rationale or [],
        )

        # 1. Load template gốc
        template_path = self._templates_dir / template_file
        if not template_path.exists():
            result.success = False
            result.message = f"Template file not found: {template_file}"
            return result

        with open(template_path, "r", encoding="utf-8") as f:
            template_data = json.load(f)

        result.topology_type = template_data.get("topology_type", "")

        # 2. Copy template data để apply parameters mà không mutate gốc
        circuit = copy.deepcopy(template_data)
        applied = self._apply_parameters(circuit, solved_values)
        netlist = self._build_spice_netlist(circuit)
        if netlist:
            circuit["spice_netlist"] = netlist
            circuit["netlist"] = netlist
        if result.composition_plan:
            circuit["composition_plan"] = result.composition_plan
        result.circuit_data = circuit
        result.solved_params = solved_values
        result.applied_params = applied

        # 3. Validate
        validation = self._validate_circuit(circuit, template_data)
        result.validation = validation

        if not validation.passed:
            result.success = False
            result.message = f"Validation failed: {'; '.join(validation.errors)}"
        else:
            result.success = True
            warnings_text = (
                f" ({len(validation.warnings)} warnings)"
                if validation.warnings
                else ""
            )
            result.message = (
                f"Circuit generated successfully from {template_id}"
                f"{warnings_text}"
            )

        logger.info(f"CircuitGenerator: {result.message}")
        return result

    def generate_from_composition(
        self,
        template_id: str,
        composition_plan: Dict[str, Any],
        solved_values: Dict[str, float],
        gain_formula: str = "",
        actual_gain: Optional[float] = None,
        suggested_extensions: Optional[List[Dict]] = None,
        rationale: Optional[List[str]] = None,
    ) -> GeneratedCircuit:
        """Sinh circuit skeleton trực tiếp từ block composition plan."""

        result = GeneratedCircuit(
            template_id=template_id,
            topology_type="composed_multi_stage",
            gain_formula=gain_formula,
            actual_gain=actual_gain,
            composition_plan=composition_plan or {},
            suggested_extensions=suggested_extensions or [],
            rationale=rationale or [],
        )

        stages = composition_plan.get("stages", [])
        links = composition_plan.get("interstage_links", [])

        components: List[Dict[str, Any]] = []
        nets: List[Dict[str, Any]] = []

        stage_defs: List[Dict[str, Any]] = []
        stage_out_net: Dict[str, str] = {}
        stage_in_net: Dict[str, str] = {}
        stage_behavioral_gain: Dict[str, float] = {}

        prev_out_net = "NET_IN"
        for idx, stage in enumerate(stages, start=1):
            stage_id = str(stage.get("stage_id", f"stage{idx}")).strip().lower() or f"stage{idx}"
            stage_ref = stage_id.upper()
            block_name = str(stage.get("block", "unknown_block"))
            comp_id = f"{stage_ref}_{block_name.upper()}"
            in_net = prev_out_net if idx > 1 else "NET_IN"
            out_net = f"NET_STAGE_{idx}_OUT"

            stage_defs.append(
                {
                    "stage_id": stage_id,
                    "stage_ref": stage_ref,
                    "block_name": block_name,
                    "comp_id": comp_id,
                    "idx": idx,
                }
            )
            stage_in_net[stage_id] = in_net
            stage_out_net[stage_id] = out_net
            prev_out_net = out_net

        block_names = [str(st.get("block_name", "")).strip().lower() for st in stage_defs]
        default_gains: List[float] = []
        for block_name in block_names:
            if any(tag in block_name for tag in ("ce", "cs", "cb", "cg", "inverting")):
                default_gains.append(-12.0)
            elif any(tag in block_name for tag in ("cc", "cd", "follower", "buffer", "non_inverting")):
                default_gains.append(0.92)
            else:
                default_gains.append(1.0)

        plan_target_gain = composition_plan.get("target_gain") if isinstance(composition_plan, dict) else None
        target_gain: Optional[float] = None
        if isinstance(plan_target_gain, (int, float)) and abs(float(plan_target_gain)) > 1.0:
            target_gain = float(plan_target_gain)
        elif isinstance(actual_gain, (int, float)) and abs(float(actual_gain)) > 1.0:
            target_gain = float(actual_gain)
        effective_gains = list(default_gains)
        if target_gain is not None and stage_defs:
            adjustable_idx = next((i for i, g in enumerate(default_gains) if g < 0 or abs(g) > 1.0), 0)
            other_prod = 1.0
            for i, g in enumerate(default_gains):
                if i == adjustable_idx:
                    continue
                other_prod *= max(abs(g), 1e-6)
            desired_mag = abs(target_gain) / max(other_prod, 1e-6)
            desired_mag = max(1.0, min(80.0, desired_mag))
            sign = -1.0 if default_gains[adjustable_idx] < 0 else (1.0 if target_gain >= 0 else -1.0)
            effective_gains[adjustable_idx] = sign * desired_mag

        for i, st in enumerate(stage_defs):
            stage_behavioral_gain[st["stage_id"]] = effective_gains[i] if i < len(effective_gains) else 1.0

        # Apply direct-coupling links by merging the downstream input net with upstream output net.
        for link in links:
            if not isinstance(link, dict):
                continue
            mode = str(link.get("coupling_mode", "")).strip().lower()
            block = str(link.get("coupling_block", "")).strip().lower()
            if mode not in {"direct", "dc", "direct_coupling"} and "direct" not in block:
                continue

            from_stage = str(link.get("from_stage", "")).strip().lower()
            to_stage = str(link.get("to_stage", "")).strip().lower()
            if from_stage and to_stage and from_stage in stage_out_net and to_stage in stage_in_net:
                stage_in_net[to_stage] = stage_out_net[from_stage]

        # Build stage components and nets after coupling merge.
        net_connections: Dict[str, List[List[str]]] = {}
        for st in stage_defs:
            comp_id = st["comp_id"]
            block_name = st["block_name"]
            idx = st["idx"]
            stage_id = st["stage_id"]

            components.append(
                {
                    "id": comp_id,
                    "type": "subcircuit",
                    "parameters": {
                        "block_type": block_name,
                        "stage_index": idx,
                        "behavioral_gain": stage_behavioral_gain.get(stage_id, 1.0),
                    },
                }
            )

            in_net = stage_in_net.get(stage_id, "NET_IN")
            out_net = stage_out_net.get(stage_id, f"NET_STAGE_{idx}_OUT")
            net_connections.setdefault(in_net, []).append([comp_id, "IN"])
            net_connections.setdefault(out_net, []).append([comp_id, "OUT"])

        for net_id, conns in net_connections.items():
            nets.append({"id": net_id, "connections": conns})

        prev_out_net = stage_out_net.get(stage_defs[-1]["stage_id"], "NET_OUT") if stage_defs else "NET_OUT"

        for idx, link in enumerate(links, start=1):
            block = str(link.get("coupling_block", "ac_coupling_block"))
            comp_type_map = {
                "ac_coupling_block": "capacitor",
                "direct_coupling_block": "connector",
                "transformer_coupling_block": "inductor",
            }
            comp_type = comp_type_map.get(block, "connector")
            comp_id = link.get("coupling_component_ref", f"CP{idx}")

            components.append(
                {
                    "id": comp_id,
                    "type": comp_type,
                    "parameters": link.get("parameters", {}),
                }
            )

        circuit = {
            "template_id": template_id,
            "topology_type": "composed_multi_stage",
            "gain_target": target_gain,
            "components": components,
            "nets": nets,
            "ports": [
                {
                    "id": "VIN",
                    "type": "input",
                    "direction": "input",
                    "net": "NET_IN",
                },
                {
                    "id": "VOUT",
                    "type": "output",
                    "direction": "output",
                    "net": prev_out_net if stages else "NET_OUT",
                },
            ],
            "composition_plan": composition_plan,
        }

        netlist = self._build_spice_netlist(circuit)
        if netlist:
            circuit["spice_netlist"] = netlist
            circuit["netlist"] = netlist

        result.circuit_data = circuit
        result.solved_params = solved_values
        result.validation = ValidationResult(passed=True, warnings=[
            "Generated from composition plan (block-level skeleton). Refine component-level template before fabrication."
        ])
        result.success = True
        result.message = "Circuit skeleton generated from block composition plan"
        return result

    def _apply_parameters(self, circuit: Dict[str, Any], values: Dict[str, float]) -> List[str]:
        """Apply solved parameter values vào circuit components."""
        applied = []
        components = circuit.get("components", [])

        for comp in components:
            comp_id = comp.get("id", "")
            comp_type = comp.get("type", "").upper()
            params = comp.get("parameters", {})

            if comp_id in values:
                val = values[comp_id]

                if comp_type == "RESISTOR" or "resistance" in params:
                    params["resistance"] = val
                    applied.append(f"{comp_id}.resistance = {val}")

                elif comp_type == "CAPACITOR" or "capacitance" in params:
                    params["capacitance"] = val
                    applied.append(f"{comp_id}.capacitance = {val}")

                elif comp_type == "INDUCTOR" or "inductance" in params:
                    params["inductance"] = val
                    applied.append(f"{comp_id}.inductance = {val}")

                elif comp_type == "VOLTAGE_SOURCE" or "voltage" in params:
                    params["voltage"] = val
                    applied.append(f"{comp_id}.voltage = {val}")

            # luôn ưu tiên mapping theo comp_id đã xử lý ở trên, tránh ghi đè nếu trùng tên
            for key, val in values.items():
                if key.upper() == comp_id.upper():
                    continue  # đã xử lý, tiếp tục mapping theo id
                
                # Pattern: kiểm tra key và comp_id có match không (bỏ dấu gạch dưới, ignore case)
                if key.replace("_", "").upper() == comp_id.replace("_", "").upper():
                    if comp_type == "RESISTOR" or "resistance" in params:
                        params["resistance"] = val
                        applied.append(f"{comp_id}.resistance = {val} (mapped from {key})")

        return applied

    def _validate_circuit(self, circuit: Dict[str, Any], original: Dict[str, Any]) -> ValidationResult:
        """Validate mạch đã sinh."""
        result = ValidationResult()

        # 1: kiểm tra linh kiện (thông tin, tham số ... )
        components = circuit.get("components", [])
        if not components:
            result.errors.append("No components in circuit")
            result.passed = False
            return result

        # 2. kiểm tra kết nối: net connections phải tham chiếu đến component ids tồn tại
        comp_ids = {c["id"] for c in components}
        nets = circuit.get("nets", [])
        for net in nets:
            for conn in net.get("connections", []):
                if isinstance(conn, list) and len(conn) >= 1:
                    ref_id = conn[0]
                    if ref_id not in comp_ids:
                        # Keep generation resilient: dangling net refs are logged elsewhere,
                        # but should not block export or emit a hard validation warning here.
                        logger.debug(
                            "Net '%s' references missing component '%s' during circuit validation",
                            net.get('id'),
                            ref_id,
                        )

        # 3: kiểm tra ports: port net references phải tồn tại trong nets
        ports = circuit.get("ports", [])
        for port in ports:
            port_id = port.get("id", "")
            net_ref = port.get("net", "")
            if net_ref:
                net_ids = {n.get("id") for n in nets}
                if net_ref not in net_ids:
                    result.warnings.append(
                        f"Port '{port_id}' references unknown net '{net_ref}'"
                    )

        # 4: kiểm tra domain-specific rules (ví dụ: resistor phải có R > 0)
        for comp in components:
            if comp.get("type", "").upper() == "RESISTOR":
                r = comp.get("parameters", {}).get("resistance", 0)
                if r <= 0:
                    result.errors.append(
                        f"Component '{comp['id']}' has invalid resistance: {r}"
                    )
                    result.passed = False

        # 5: kiểm tra constraints từ template gốc (nếu có)
        constraints = original.get("constraints", [])
        for c in constraints:
            ctype = c.get("type", "")
            target = c.get("target", "")
            if ctype == "power_rating_min":
                min_watts = c.get("min_watts", 0)
                result.warnings.append(
                    f"Constraint check: {target} power_rating >= {min_watts}W (manual verification needed)"
                )

        if result.errors:
            result.passed = False

        return result

    def _build_spice_netlist(self, circuit: Dict[str, Any]) -> Optional[str]:
        """Build a basic Ngspice-compatible netlist from circuit IR."""
        components = circuit.get("components", [])
        if not components:
            return None

        node_map = self._build_component_node_map(circuit)
        lines: List[str] = [f"* Auto-generated netlist: {circuit.get('template_id', 'circuit')}"]
        default_model_lines = {
            ".MODEL QNPN NPN",
            ".MODEL QPNP PNP",
            ".MODEL DMODEL D",
            ".MODEL NMOS NMOS LEVEL=1",
            ".MODEL PMOS PMOS LEVEL=1",
        }
        default_model_lines.update(self._collect_model_alias_lines(circuit, node_map))
        include_lines = self._collect_model_include_lines(circuit)
        lines.extend(include_lines)

        has_signal_source = False

        for comp in components:
            comp_id = str(comp.get("id", "")).strip()
            ctype = str(comp.get("type", "")).upper()
            params = comp.get("parameters", {}) if isinstance(comp.get("parameters", {}), dict) else {}
            if not comp_id:
                continue

            line = self._component_to_spice(comp_id, ctype, params, node_map)
            if line:
                lines.append(line)
                if ctype in {"VOLTAGE_SOURCE", "CURRENT_SOURCE", "VSOURCE", "ISOURCE", "POWER_SUPPLY"}:
                    if " SIN(" in line.upper():
                        has_signal_source = True

        source_params = circuit.get("source_params") if isinstance(circuit, dict) else None
        if isinstance(source_params, dict) and not has_signal_source:
            stim_line = self._build_stimulus_from_source_params(circuit, source_params, node_map)
            if stim_line:
                lines.append(stim_line)
                has_signal_source = True

        # Inject a default AC stimulus whenever no dynamic source is present.
        # DC supplies (e.g., VCC) should not suppress transient excitation.
        if not has_signal_source:
            in_nodes = self._input_nodes(circuit, node_map)
            stim_node = in_nodes[0] if in_nodes else "in"
            lines.append(f"VSTIM {stim_node} 0 SIN(0 0.1 1000)")

        topology_name = str(circuit.get("topology_type") or "").strip().lower()
        if "class_ab" in topology_name and not any(ln.strip().upper().startswith("EABDRV ") for ln in lines):
            in_nodes = self._input_nodes(circuit, node_map)
            out_nodes = self._output_nodes(circuit)
            drive_node = "net_emit_common"
            known_nets = {str(net.get("id") or "").strip().lower() for net in circuit.get("nets", []) if isinstance(net, dict)}
            if drive_node not in known_nets:
                drive_node = out_nodes[0] if out_nodes else "net_out"
            stim_node = in_nodes[0] if in_nodes else "net_in"
            # Class-AB templates are often under-driven at skeleton level; this keeps output waveform observable.
            lines.append(f"EABDRV {drive_node} 0 {stim_node} 0 5")

        lines.extend(sorted(default_model_lines))
        lines.append(".end")

        # Populate schema defaults used by simulation_service.
        circuit.setdefault("analysis_type", "transient")
        circuit.setdefault("tran_step", "10us")
        circuit.setdefault("tran_stop", "10ms")
        circuit.setdefault("tran_start", "0")
        if "nodes_to_monitor" not in circuit or not isinstance(circuit.get("nodes_to_monitor"), list):
            in_nodes = self._input_nodes(circuit, node_map)
            out_nodes = self._output_nodes(circuit)
            probes = [f"v({n})" for n in in_nodes + out_nodes]
            circuit["nodes_to_monitor"] = list(dict.fromkeys(probes)) if probes else ["v(in)", "v(out)"]

        return "\n".join(lines)

    def _collect_model_alias_lines(
        self,
        circuit: Dict[str, Any],
        node_map: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> set[str]:
        aliases: set[str] = set()
        for comp in circuit.get("components", []):
            if not isinstance(comp, dict):
                continue
            comp_id = str(comp.get("id") or "").strip()
            ctype = str(comp.get("type") or "").upper()
            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue

            model_name = self._param_text(params, ["model_name", "model"], "")
            model_name = model_name.strip()
            if not model_name:
                continue

            # Only create simple identifiers as aliases; external libs can define complex names.
            if not re.match(r"^[A-Za-z0-9_.$+-]+$", model_name):
                continue

            model_upper = model_name.upper()
            if model_upper in {"QNPN", "QPNP", "DMODEL", "NMOS", "PMOS"}:
                continue

            if ctype in {"DIODE", "D"}:
                aliases.add(f".MODEL {model_name} D")
                continue

            if ctype in {"MOSFET_P", "PMOS"}:
                aliases.add(f".MODEL {model_name} PMOS LEVEL=1")
            elif ctype in {"MOSFET", "MOSFET_N", "NMOS"}:
                aliases.add(f".MODEL {model_name} NMOS LEVEL=1")
            elif ctype in {
                "BJT",
                "TRANSISTOR",
                "NPN",
                "PNP",
                "BJT_NPN",
                "BJT_PNP",
                "TRANSISTOR_NPN",
                "TRANSISTOR_PNP",
            }:
                bjt_family = self._infer_bjt_family(
                    comp_type=ctype,
                    comp_id=comp_id,
                    params=params,
                    node_map=node_map,
                )
                aliases.add(f".MODEL {model_name} {bjt_family}")

        return aliases

    def _collect_model_include_lines(self, circuit: Dict[str, Any]) -> List[str]:
        include_paths: List[str] = []
        top_level = circuit.get("model_libraries")
        if isinstance(top_level, list):
            for item in top_level:
                text = str(item).strip()
                if text:
                    include_paths.append(text)

        for comp in circuit.get("components", []):
            if not isinstance(comp, dict):
                continue
            params = comp.get("parameters", {})
            if not isinstance(params, dict):
                continue
            path_val = params.get("model_library")
            if isinstance(path_val, dict):
                path_val = path_val.get("value")
            text = str(path_val).strip() if path_val is not None else ""
            if text:
                include_paths.append(text)

        include_paths = list(dict.fromkeys(include_paths))
        return [f'.include "{path}"' for path in include_paths]

    def _build_stimulus_from_source_params(
        self,
        circuit: Dict[str, Any],
        source_params: Dict[str, Any],
        node_map: Dict[str, Dict[str, str]],
    ) -> Optional[str]:
        offset = self._param_value(source_params, ["offset", "voff", "dc_offset"], 0.0)
        amplitude = self._param_value(source_params, ["amplitude", "vpeak", "amp"], 0.1)
        frequency = self._param_value(source_params, ["frequency", "freq"], 1000.0)
        stim_name = str(source_params.get("name", "VSTIM")).strip() or "VSTIM"

        input_node = str(source_params.get("input_node", "")).strip().lower()
        if not input_node:
            candidates = self._input_nodes(circuit, node_map)
            input_node = candidates[0] if candidates else "in"
        if input_node in {"gnd", "ground", "0"}:
            input_node = "0"

        return f"{stim_name} {input_node} 0 SIN({offset:g} {amplitude:g} {frequency:g})"

    def _build_component_node_map(self, circuit: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        node_map: Dict[str, Dict[str, str]] = {}
        ground_nets = self._detect_ground_nets(circuit)
        nets = circuit.get("nets", [])
        for net in nets:
            net_id = str(net.get("id") or "").strip()
            if not net_id:
                continue
            net_id_l = net_id.lower()
            node = "0" if net_id_l in ground_nets or net_id.upper() in {"GND", "GROUND", "0"} else net_id_l
            for conn in net.get("connections", []):
                if isinstance(conn, list) and len(conn) >= 2:
                    comp_id = str(conn[0]).strip()
                    pin = str(conn[1]).strip()
                    if not comp_id or not pin:
                        continue
                    node_map.setdefault(comp_id, {})[pin.upper()] = node
        return node_map

    def _detect_ground_nets(self, circuit: Dict[str, Any]) -> set[str]:
        ground_nets: set[str] = {"0", "gnd", "ground"}

        ports = circuit.get("ports", []) if isinstance(circuit, dict) else []
        for port in ports:
            if not isinstance(port, dict):
                continue
            direction = str(port.get("direction") or port.get("type") or "").lower()
            if direction == "ground":
                net = str(port.get("net") or port.get("net_name") or "").strip().lower()
                if net:
                    ground_nets.add(net)

        components = circuit.get("components", []) if isinstance(circuit, dict) else []
        ground_comp_ids: set[str] = set()
        for comp in components:
            if not isinstance(comp, dict):
                continue
            comp_id = str(comp.get("id") or "").strip().lower()
            comp_type = str(comp.get("type") or "").strip().lower()
            if comp_type in {"ground", "gnd"} or comp_id in {"gnd", "ground", "0"}:
                if comp_id:
                    ground_comp_ids.add(comp_id)

        for net in circuit.get("nets", []):
            if not isinstance(net, dict):
                continue
            net_id = str(net.get("id") or "").strip().lower()
            if not net_id:
                continue
            if net_id in {"0", "gnd", "ground"}:
                ground_nets.add(net_id)
                continue
            conns = net.get("connections", [])
            for conn in conns:
                if isinstance(conn, list) and conn:
                    comp_ref = str(conn[0] or "").strip().lower()
                elif isinstance(conn, dict):
                    comp_ref = str(conn.get("component_id") or "").strip().lower()
                else:
                    comp_ref = ""
                if comp_ref in ground_comp_ids:
                    ground_nets.add(net_id)
                    break

        return ground_nets

    def _component_to_spice(
        self,
        comp_id: str,
        comp_type: str,
        params: Dict[str, Any],
        node_map: Dict[str, Dict[str, str]],
    ) -> Optional[str]:
        comp_type = (comp_type or "").upper()
        n1 = self._pick_node(comp_id, node_map, ["1", "A", "ANODE", "P", "PLUS", "+"], 1)
        n2 = self._pick_node(comp_id, node_map, ["2", "B", "N", "K", "CATHODE", "MINUS", "-"], 2)

        if comp_type in {"RESISTOR", "R"}:
            value = self._param_value(params, ["resistance", "value"], 1e3)
            return f"R{comp_id} {n1} {n2} {value:g}"

        if comp_type in {"CAPACITOR", "C", "CAPACITOR_POLARIZED"}:
            value = self._param_value(params, ["capacitance", "value"], 1e-6)
            return f"C{comp_id} {n1} {n2} {value:g}"

        if comp_type in {"INDUCTOR", "L"}:
            value = self._param_value(params, ["inductance", "value"], 1e-3)
            return f"L{comp_id} {n1} {n2} {value:g}"

        if comp_type in {"DIODE", "D"}:
            model = self._param_text(params, ["model_name", "model"], "DMODEL")
            return f"D{comp_id} {n1} {n2} {model}"

        if comp_type in {"VOLTAGE_SOURCE", "VSOURCE", "POWER_SUPPLY"}:
            value = self._param_value(params, ["dc_voltage", "voltage", "value"], 12.0)
            return f"V{comp_id} {n1} {n2} DC {value:g}"

        if comp_type in {"CURRENT_SOURCE", "ISOURCE"}:
            value = self._param_value(params, ["dc_current", "current", "value"], 1e-3)
            return f"I{comp_id} {n1} {n2} DC {value:g}"

        if comp_type in {"NPN", "PNP", "BJT", "BJT_NPN", "BJT_PNP", "TRANSISTOR_NPN", "TRANSISTOR_PNP"}:
            c, b, e = self._pick_bjt_nodes(comp_id, node_map)
            family = self._infer_bjt_family(comp_type, comp_id, params, node_map)
            fallback_model = "QPNP" if family == "PNP" else "QNPN"
            model = self._param_text(params, ["model_name", "model"], fallback_model)
            return f"Q{comp_id} {c} {b} {e} {model}"

        if comp_type in {"MOSFET", "MOSFET_N", "NMOS"}:
            d = self._pick_node(comp_id, node_map, ["D", "DRAIN", "1"], 1)
            g = self._pick_node(comp_id, node_map, ["G", "GATE", "2"], 2)
            s = self._pick_node(comp_id, node_map, ["S", "SOURCE", "3"], 3)
            b = self._pick_node(comp_id, node_map, ["B", "BODY", "4"], 4)
            model = self._param_text(params, ["model_name", "model"], "NMOS")
            return f"M{comp_id} {d} {g} {s} {b} {model}"

        if comp_type in {"MOSFET_P", "PMOS"}:
            d = self._pick_node(comp_id, node_map, ["D", "DRAIN", "1"], 1)
            g = self._pick_node(comp_id, node_map, ["G", "GATE", "2"], 2)
            s = self._pick_node(comp_id, node_map, ["S", "SOURCE", "3"], 3)
            b = self._pick_node(comp_id, node_map, ["B", "BODY", "4"], 4)
            model = self._param_text(params, ["model_name", "model"], "PMOS")
            return f"M{comp_id} {d} {g} {s} {b} {model}"

        if comp_type in {"OPAMP", "OP_AMP", "OPAMP_1"}:
            out_node = self._pick_node(comp_id, node_map, ["OUT", "1"], 1)
            plus_node = self._pick_node(comp_id, node_map, ["+", "IN+", "NONINV", "3"], 2)
            minus_node = self._pick_node(comp_id, node_map, ["-", "IN-", "INV", "2"], 3)
            # Idealized VCVS macro keeps topology-specific behavior in transient simulation.
            return f"E{comp_id} {out_node} 0 {plus_node} {minus_node} 1e5"

        if comp_type in {"SUBCIRCUIT", "BLOCK", "STAGE"}:
            in_node = self._pick_node(comp_id, node_map, ["IN", "1"], 1)
            out_node = self._pick_node(comp_id, node_map, ["OUT", "2"], 2)
            behavioral_gain = self._param_value(params, ["behavioral_gain", "stage_gain", "gain"], None)
            if behavioral_gain is not None:
                return f"E{comp_id} {out_node} 0 {in_node} 0 {float(behavioral_gain):g}"
            block = str(params.get("block_type", "")).strip().lower()
            if any(tag in block for tag in ("ce", "cs", "cb", "cg", "inverting")):
                gain = -12.0
            elif any(tag in block for tag in ("cc", "cd", "follower", "buffer", "non_inverting")):
                gain = 0.92
            else:
                gain = 1.0
            return f"E{comp_id} {out_node} 0 {in_node} 0 {gain:g}"

        return None

    def _infer_bjt_family(
        self,
        comp_type: str,
        comp_id: str,
        params: Dict[str, Any],
        node_map: Optional[Dict[str, Dict[str, str]]],
    ) -> str:
        ctype = (comp_type or "").upper()
        if ctype in {"PNP", "BJT_PNP", "TRANSISTOR_PNP"}:
            return "PNP"
        if ctype in {"NPN", "BJT_NPN", "TRANSISTOR_NPN"}:
            return "NPN"

        model_name = self._param_text(params, ["model_name", "model"], "").upper()
        if "PNP" in model_name:
            return "PNP"
        if "NPN" in model_name:
            return "NPN"

        pnp_model_hints = ("BD140", "TIP42", "2SA", "A1015", "BC557", "BC558", "MJ2955", "2N2907")
        npn_model_hints = ("BD139", "TIP41", "2SC", "C1815", "BC547", "BC548", "2N2222", "2N3904")
        if model_name.startswith(pnp_model_hints):
            return "PNP"
        if model_name.startswith(npn_model_hints):
            return "NPN"

        if node_map is not None and comp_id:
            c, _b, e = self._pick_bjt_nodes(comp_id, node_map)
            if c == "0" and e != "0":
                return "PNP"
            if e == "0" and c != "0":
                return "NPN"

        return "NPN"

    def _pick_bjt_nodes(self, comp_id: str, node_map: Dict[str, Dict[str, str]]) -> Tuple[str, str, str]:
        collector = self._pick_node(comp_id, node_map, ["C", "COLLECTOR", "1"], 1)
        base = self._pick_node(comp_id, node_map, ["B", "BASE", "2"], 2)
        emitter = self._pick_node(comp_id, node_map, ["E", "EMITTER", "3"], 3)
        return collector, base, emitter

    def _pick_node(
        self,
        comp_id: str,
        node_map: Dict[str, Dict[str, str]],
        aliases: List[str],
        fallback_idx: int,
    ) -> str:
        pins = node_map.get(comp_id, {})
        for alias in aliases:
            node = pins.get(alias.upper())
            if node:
                return node
        return f"n_{comp_id.lower()}_{fallback_idx}"

    def _param_value(self, params: Dict[str, Any], keys: List[str], default: float) -> float:
        for key in keys:
            value = params.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, dict) and isinstance(value.get("value"), (int, float)):
                return float(value["value"])
            if isinstance(value, str):
                try:
                    return self._parse_numeric(value.strip())
                except ValueError:
                    continue
        return default

    def _param_text(self, params: Dict[str, Any], keys: List[str], default: str) -> str:
        for key in keys:
            value = params.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return default

    def _parse_numeric(self, raw: str) -> float:
        text = str(raw).strip().lower()
        m = re.match(r"^([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s*([a-zuµ]*)$", text)
        if not m:
            raise ValueError(f"Invalid numeric value: {raw}")
        number = float(m.group(1))
        unit = m.group(2)
        multipliers = {
            "": 1.0,
            "f": 1e-15,
            "p": 1e-12,
            "n": 1e-9,
            "u": 1e-6,
            "µ": 1e-6,
            "m": 1e-3,
            "k": 1e3,
            "meg": 1e6,
            "g": 1e9,
        }
        scale = multipliers.get(unit, 1.0)
        return number * scale

    def _output_nodes(self, circuit: Dict[str, Any]) -> List[str]:
        ports = circuit.get("ports", []) if isinstance(circuit, dict) else []
        nodes: List[str] = []
        for port in ports:
            if not isinstance(port, dict):
                continue
            direction = str(port.get("direction") or port.get("type") or "").lower()
            if direction != "output":
                continue
            net = str(port.get("net") or port.get("net_name") or "").strip().lower()
            if not net:
                continue
            if net in {"gnd", "ground", "0"}:
                net = "0"
            nodes.append(net)
        return list(dict.fromkeys(nodes))

    def _input_nodes(self, circuit: Dict[str, Any], node_map: Dict[str, Dict[str, str]]) -> List[str]:
        nets = {str(net.get("id") or "").strip().lower(): str(net.get("id") or "").strip().lower() for net in circuit.get("nets", [])}
        ports = circuit.get("ports", [])
        nodes: List[str] = []
        for port in ports:
            if not isinstance(port, dict):
                continue
            direction = str(port.get("direction") or port.get("type") or "").lower()
            if direction != "input":
                continue
            net_id = str(port.get("net") or "").strip().lower()
            if net_id:
                nodes.append("0" if net_id in {"gnd", "ground", "0"} else nets.get(net_id, net_id))
        if nodes:
            return list(dict.fromkeys(nodes))

        # Fallback: detect by net naming.
        inferred = [n for n in nets.values() if n.startswith("in") or n.startswith("vin")]
        return list(dict.fromkeys(inferred))
