# app/domains/circuits/ai_core/ai_core.py
""" AI Core - Main Orchestrator
Điều phối 4 bước:
    Parse (yêu cầu) → Plan(chọn&ghép) → Solve (giải mã) → Generate
"""

from __future__ import annotations

import ast
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    from sympy import SympifyError, sympify
except Exception:  # pragma: no cover - optional dependency guard
    SympifyError = ValueError
    sympify = None

from app.application.ai.circuit_ir_schema import CircuitIR

from .spec_parser import NLPSpecParser, UserSpec
from .metadata_repo import MetadataRepository
from .topology_planner import TopologyPlanner, TopologyPlan
from .parameter_solver import ParameterSolver, SolvedParams
from .circuit_generator import CircuitGenerator, GeneratedCircuit

""" Lý do sử dụng thư viện
__future__ annotations: tham chiếu đến biến/thamsố/giátrị trước khi tạo xong.
logging : ghi log hoạt động của hệ thống để theo dõi và gỡ lỗi.
_dataclass : tạo lớp dữ liệu đơn giản để lưu trữ kết quả pipeline.
Path : quản lý đường dẫn file và thư mục một cách dễ dàng.
typing : cung cấp kiểu dữ liệu cho hàm và biến để tăng tính rõ ràng.

NLPSpecParserSpecParser, UserSpec: chuyển ngôn ngữ tự nhiên → spec cấu trúc JSON
MetadataRepository: lưu trữ kiến thức mạch điện dưới dạng blocks
TopologyPlannerogyPlanner, TopologyPlan: chọn/ghép block topology phù hợp spec
ParameterSolver, SolvedParams: giải tham số mạch (gain, R, C...) theo spec
CircuitGenerator, GeneratedCircuit: sinh circuit IR từ topology + tham số
"""


# Ghi log hoạt động
logger = logging.getLogger(__name__)

""" Pipeline: chuỗi xử lý chính core 
- Pipeline: user_text → spec → plan → solved → circuit
* user_text : dữ liệu đvao thô
* spec : kết quả phân tích đầu vào, trích xuất thông tin cấu trúc
* plan : kết quả lập kế hoạch topology, template đã chọn, blocks, lý do chọn
* solved : kết quả giải tham số, giá trị tham số, gain thực tế
* circuit : kết quả sinh mạch, dữ liệu mạch, thông điệp lỗi nếu có
* success : trạng thái thành công của pipeline
* stage_reached : giai đoạn cuối cùng đạt được (parse, plan, solve, generate)
* error : thông điệp lỗi nếu có - theo dõi tiến trình và lỗi của pipeline
"""
@dataclass
class PipelineResult:
    user_text: str = ""
    spec: Optional[UserSpec] = None
    plan: Optional[TopologyPlan] = None
    solved: Optional[SolvedParams] = None
    circuit: Optional[GeneratedCircuit] = None
    success: bool = True
    stage_reached: str = ""  # parse | plan | solve | generate
    error: str = ""


    # Pipeline thành dict -> serialize thành JSON response cho API
    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            # lưu trữ: request, trạng thái pipeline, giai đoạn đạt được, lỗi (nếu có) - theo dõi tiến trình
            "user_text": self.user_text,
            "success": self.success,
            "stage_reached": self.stage_reached,
            "error": self.error,
        }
        
        # nếu có kết quả phân tích đầu vào -> thêm thông tin về loại mạch, gain, ...
        if self.spec:
            d["spec"] = {
                "circuit_type": self.spec.circuit_type,
                "topology_candidates": self.spec.topology_candidates,
                "gain": self.spec.gain,
                "high_cmr": self.spec.high_cmr,
                "input_mode": self.spec.input_mode,
                "output_buffer": self.spec.output_buffer,
                "power_output": self.spec.power_output,
                "supply_mode": self.spec.supply_mode,
                "coupling_preference": self.spec.coupling_preference,
                "device_preference": self.spec.device_preference,
                "requested_stage_blocks": self.spec.requested_stage_blocks,
                "extra_requirements": self.spec.extra_requirements,
                "functional_features": self.spec.functional_features,
                "keyword_hits": self.spec.keyword_hits,
            }
            
        # nếu có plan về topology -> thêm thông tin về template đã chọn, mode, độ chính xác, blocks, công thức gain, lý do chọn, đề xuất mở rộng từ plan
        if self.plan:
            d["plan"] = {
                "matched_template_id": self.plan.matched_template_id,
                "mode": self.plan.mode,
                "confidence": self.plan.confidence,
                "blocks": self.plan.blocks,
                "coupling_mode": self.plan.coupling_mode,
                "synthesis_plan": self.plan.synthesis_plan,
                "gain_formula": self.plan.gain_formula,
                "rationale": self.plan.rationale,
                "suggested_extensions": self.plan.suggested_extensions,
            }
        
        # nếu đã giải tham số -> thêm thông tin về các giá trị tham số, công thức gain thực tế, ghi chú, cảnh báo
        if self.solved:
            d["solved"] = {
                "values": self.solved.values,
                "gain_formula": self.solved.gain_formula,
                "actual_gain": self.solved.actual_gain,
                "notes": self.solved.notes,
                "warnings": self.solved.warnings,
            }
        
        # nếu đã sinh được circuit -> thêm thông tin về thành công, dữ liệu mạch, thông điệp
        if self.circuit:
            d["circuit"] = self.circuit.to_dict()
        return d


class InvalidPinConnectionError(ValueError):
    """Raised when a net node references an invalid component pin."""


class CircuitIRValidator:
    """Validation gate for LLM-generated CircuitIR.

    Provides:
    - Math validation/fix for calculation entries
    - Physics pin validation against component pin policies
    """

    _PIN_POLICY: Dict[str, Set[str]] = {
        "resistor": {"1", "2"},
        "capacitor": {"1", "2"},
        "inductor": {"1", "2"},
        "npn": {"B", "C", "E", "1", "2", "3"},
        "pnp": {"B", "C", "E", "1", "2", "3"},
        "opamp": {"1", "2", "3", "4", "5", "6", "7", "8", "IN+", "IN-", "OUT", "V+", "V-"},
        "voltage_source": {"1", "2", "+", "-"},
        "current_source": {"1", "2", "+", "-"},
        "diode": {"A", "K", "1", "2"},
    }

    _TYPE_ALIASES: Dict[str, str] = {
        "r": "resistor",
        "res": "resistor",
        "resistor": "resistor",
        "c": "capacitor",
        "cap": "capacitor",
        "capacitor": "capacitor",
        "l": "inductor",
        "inductor": "inductor",
        "q_npn": "npn",
        "q_pnp": "pnp",
        "npn": "npn",
        "pnp": "pnp",
        "bjt": "npn",
        "bjt_npn": "npn",
        "bjt_pnp": "pnp",
        "opamp": "opamp",
        "op_amp": "opamp",
        "vsource": "voltage_source",
        "voltage_source": "voltage_source",
        "isource": "current_source",
        "current_source": "current_source",
        "diode": "diode",
        "d": "diode",
    }

    _UNIT_SUFFIX_SCALE: Dict[str, float] = {
        "k": 1e3,
        "m": 1e-3,
        "u": 1e-6,
        "n": 1e-9,
        "p": 1e-12,
        "g": 1e9,
    }

    def __init__(self, relative_error_threshold: float = 0.05) -> None:
        self.relative_error_threshold = max(0.0, float(relative_error_threshold))

    def validate_and_fix_math(self, ir: CircuitIR) -> CircuitIR:
        """Recompute formulas, fix hallucinated values, and sync component values.

        If relative error > 5% (default), the calculated value is corrected and the
        target component value is updated to the corrected number.
        """
        if not ir.calculations:
            return ir

        symbol_table = self._build_symbol_table(ir)
        fixed_values_by_ref: Dict[str, float] = {}
        updated_calculations = []
        calc_changed = False

        for calc in ir.calculations:
            corrected = calc
            computed = self._compute_formula(calc.formula, symbol_table)

            if computed is None or not math.isfinite(computed):
                updated_calculations.append(corrected)
                continue

            expected = float(calc.calculated_value)
            rel_err = self._relative_error(expected, computed)
            if rel_err > self.relative_error_threshold:
                logger.warning(
                    "Math mismatch for %s: expected=%s computed=%s rel_err=%.4f. Auto-fixing.",
                    calc.target_component,
                    expected,
                    computed,
                    rel_err,
                )
                corrected = calc.model_copy(update={"calculated_value": computed})
                fixed_values_by_ref[calc.target_component.strip().upper()] = computed
                calc_changed = True

            symbol_table[calc.target_component.strip().upper()] = float(corrected.calculated_value)
            symbol_table[calc.target_component.strip().lower()] = float(corrected.calculated_value)
            updated_calculations.append(corrected)

        updated_components = []
        comp_changed = False
        for comp in ir.components:
            ref_upper = comp.ref_id.strip().upper()
            if ref_upper in fixed_values_by_ref:
                comp_changed = True
                updated_components.append(comp.model_copy(update={"value": fixed_values_by_ref[ref_upper]}))
            else:
                updated_components.append(comp)

        if not calc_changed and not comp_changed:
            return ir

        return ir.model_copy(
            update={
                "calculations": updated_calculations,
                "components": updated_components,
            },
            deep=True,
        )

    def validate_pins(self, ir: CircuitIR) -> None:
        """Validate net node references against component existence and pin policy."""
        component_by_ref = {comp.ref_id.strip().upper(): comp for comp in ir.components}

        for net in ir.nets:
            for node in net.nodes:
                if ":" not in node:
                    raise InvalidPinConnectionError(
                        f"Invalid node format '{node}' in net '{net.net_name}'. Expected REF:PIN"
                    )

                raw_ref, raw_pin = node.split(":", 1)
                ref_id = raw_ref.strip().upper()
                pin_name = raw_pin.strip().upper()

                if not ref_id or not pin_name:
                    raise InvalidPinConnectionError(
                        f"Invalid node format '{node}' in net '{net.net_name}'. Expected REF:PIN"
                    )

                component = component_by_ref.get(ref_id)
                if component is None:
                    raise InvalidPinConnectionError(
                        f"Net '{net.net_name}' references unknown component '{ref_id}'"
                    )

                allowed_pins = self._resolve_allowed_pins(component.type)
                if not allowed_pins:
                    raise InvalidPinConnectionError(
                        f"No pin policy defined for component type '{component.type}' ({component.ref_id})"
                    )

                if pin_name not in allowed_pins:
                    raise InvalidPinConnectionError(
                        f"Invalid pin '{raw_pin}' for component '{component.ref_id}' "
                        f"(type={component.type}). Allowed pins: {sorted(allowed_pins)}"
                    )

    def _build_symbol_table(self, ir: CircuitIR) -> Dict[str, float]:
        table: Dict[str, float] = {
            "pi": math.pi,
            "e": math.e,
        }

        for comp in ir.components:
            val = self._to_numeric(comp.value)
            if val is None:
                continue
            table[comp.ref_id.strip().upper()] = val
            table[comp.ref_id.strip().lower()] = val

        for calc in ir.calculations:
            target = calc.target_component.strip()
            try:
                numeric = float(calc.calculated_value)
            except (TypeError, ValueError):
                continue
            table[target.upper()] = numeric
            table[target.lower()] = numeric

        return table

    def _compute_formula(self, formula: str, symbol_table: Dict[str, float]) -> Optional[float]:
        raw = (formula or "").strip()
        if not raw:
            return None

        expr = self._sanitize_formula_expression(raw)
        if not expr:
            return None

        try:
            if sympify is not None:
                value = sympify(expr, locals=symbol_table)
                return float(value.evalf())
        except (SympifyError, TypeError, ValueError) as exc:
            logger.warning("sympy evaluation failed for formula '%s': %s", formula, exc)
        except Exception as exc:  # pragma: no cover - conservative runtime guard
            logger.warning("Unexpected sympy error for formula '%s': %s", formula, exc)

        try:
            return float(self._safe_eval_with_ast(expr, symbol_table))
        except Exception as exc:
            logger.warning("AST evaluator failed for formula '%s': %s", formula, exc)
            return None

    def _sanitize_formula_expression(self, formula: str) -> str:
        expr = [part.strip() for part in formula.split("=") if part.strip()]
        candidate = expr[-1] if expr else formula

        candidate = candidate.replace("×", "*").replace("÷", "/").replace("^", "**")
        candidate = candidate.replace(",", "")

        def _expand_metric(match: re.Match[str]) -> str:
            base = float(match.group("num"))
            suffix = (match.group("suffix") or "").lower()
            return str(base * self._UNIT_SUFFIX_SCALE.get(suffix, 1.0))

        candidate = re.sub(
            r"(?P<num>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(?P<suffix>[kKmMuUnNpPgG])(?=\s*(?:[A-Za-zΩ]+)?\b)",
            _expand_metric,
            candidate,
        )
        candidate = re.sub(r"(?<=\d)\s*[A-Za-zΩ]+", "", candidate)
        candidate = re.sub(r"[^0-9A-Za-z_+\-*/(). ]", " ", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip()
        return candidate

    def _safe_eval_with_ast(self, expression: str, symbols: Dict[str, float]) -> float:
        allowed_funcs = {
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "log": math.log,
            "log10": math.log10,
            "exp": math.exp,
            "abs": abs,
            "pow": pow,
        }

        names = dict(symbols)
        names.update({"pi": math.pi, "e": math.e})

        node = ast.parse(expression, mode="eval")

        def _eval(n: ast.AST) -> float:
            if isinstance(n, ast.Expression):
                return _eval(n.body)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
                return float(n.value)
            if isinstance(n, ast.Name):
                key = n.id
                if key in names:
                    return float(names[key])
                if key.upper() in names:
                    return float(names[key.upper()])
                if key.lower() in names:
                    return float(names[key.lower()])
                raise ValueError(f"Unknown symbol '{key}'")
            if isinstance(n, ast.BinOp):
                left = _eval(n.left)
                right = _eval(n.right)
                if isinstance(n.op, ast.Add):
                    return left + right
                if isinstance(n.op, ast.Sub):
                    return left - right
                if isinstance(n.op, ast.Mult):
                    return left * right
                if isinstance(n.op, ast.Div):
                    return left / right
                if isinstance(n.op, ast.Pow):
                    return left ** right
                if isinstance(n.op, ast.Mod):
                    return left % right
                raise ValueError(f"Unsupported binary operator: {type(n.op).__name__}")
            if isinstance(n, ast.UnaryOp):
                val = _eval(n.operand)
                if isinstance(n.op, ast.UAdd):
                    return val
                if isinstance(n.op, ast.USub):
                    return -val
                raise ValueError(f"Unsupported unary operator: {type(n.op).__name__}")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                func_name = n.func.id
                func = allowed_funcs.get(func_name)
                if func is None:
                    raise ValueError(f"Function '{func_name}' is not allowed")
                args = [_eval(arg) for arg in n.args]
                return float(func(*args))
            raise ValueError(f"Unsupported AST node: {type(n).__name__}")

        return float(_eval(node))

    @staticmethod
    def _to_numeric(value: Any) -> Optional[float]:
        if isinstance(value, (int, float)):
            return float(value)

        text = str(value or "").strip().replace(",", "")
        if not text:
            return None

        match = re.fullmatch(
            r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([kKmMuUnNpPgG]?)",
            text,
        )
        if not match:
            return None

        base = float(match.group(1))
        suffix = (match.group(2) or "").lower()
        scale = CircuitIRValidator._UNIT_SUFFIX_SCALE.get(suffix, 1.0)
        return base * scale

    @staticmethod
    def _relative_error(expected: float, measured: float) -> float:
        denom = max(abs(expected), 1e-12)
        return abs(measured - expected) / denom

    def _resolve_allowed_pins(self, component_type: str) -> Set[str]:
        raw = str(component_type or "").strip().lower()
        canonical = self._TYPE_ALIASES.get(raw)
        if canonical is None:
            for key, alias in self._TYPE_ALIASES.items():
                if key in raw:
                    canonical = alias
                    break
        if canonical is None:
            return set()
        return {pin.upper() for pin in self._PIN_POLICY.get(canonical, set())}


""" Xử lý điều phối của Meta-Template Layer,
Điều phối 4 bước chính của AI Core: Parse → Plan → Solve → Generate
 * parser - chuyển ngôn ngữ tự nhiên → spec cấu trúc JSON
 * repo - lưu trữ kiến thức mạch điện dưới dạng blocks (metadata + block library)
 * planner - chọn/ghép block topology phù hợp spec
 * solver - giải tham số mạch (gain, R, C...) theo spec
 * generator - sinh circuit IR từ topology + tham số
"""
class AICore:
    def __init__(self, metadata_dir: Optional[Path] = None, block_library_dir: Optional[Path] = None, templates_dir: Optional[Path] = None):
        # Khởi tạo các module
        self._parser = NLPSpecParser()

        self._repo = MetadataRepository(
            metadata_dir=metadata_dir,
            block_library_dir=block_library_dir,
        )
        self._repo.load()
        self._planner = TopologyPlanner()
        self._solver = ParameterSolver()
        self._generator = CircuitGenerator(templates_dir=templates_dir)

        logger.info(
            f"AICore initialized – {len(self._repo._metadata)} templates loaded"
        )



    #  Public API
    def handle_spec(self, spec: UserSpec) -> PipelineResult:
        """Nhận UserSpec đã parse sẵn, bỏ qua Step 1 (Parse), chạy Plan→Solve→Generate."""
        result = PipelineResult(user_text=spec.raw_text)
        result.spec = spec
        result.stage_reached = "parse"

        if not spec.circuit_type:
            result.success = False
            result.error = "Could not determine circuit type from input"
            return result

        return self._run_pipeline_from_plan(result, spec)

    def handle_request(self, user_text: str) -> PipelineResult:
        # Khởi tạo kết quả pipeline với user_text và trạng thái mặc định
        result = PipelineResult(user_text=user_text)

        # ── Step 1: Parse: NLP text -> UserSpec ──
        try:
            spec = self._parser.parse(user_text)
            result.spec = spec
            result.stage_reached = "parse"
            logger.info(f"Step 1 Parse → circuit_type={spec.circuit_type}, gain={spec.gain}")
        except Exception as e:
            result.success = False
            result.stage_reached = "parse"
            result.error = f"Parse error: {e}"
            logger.error(result.error)
            return result

        if not spec.circuit_type:
            result.success = False
            result.error = "Could not determine circuit type from input"
            return result

        return self._run_pipeline_from_plan(result, spec)

    def _run_pipeline_from_plan(self, result: PipelineResult, spec: UserSpec) -> PipelineResult:
        """Chạy Steps 2–4 (Plan → Solve → Generate) từ UserSpec đã có sẵn."""

        # ── Step 2: Plan: UserSpec -> TopologyPlan ──
        try:
            plan = self._planner.plan(spec, self._repo)
            result.plan = plan
            result.stage_reached = "plan"
            logger.info(
                f"Step 2 Plan → template={plan.matched_template_id}, "
                f"mode={plan.mode}, confidence={plan.confidence:.2f}"
            )
        except Exception as e:
            result.success = False
            result.stage_reached = "plan"
            result.error = f"Plan error: {e}"
            logger.error(result.error)
            return result

        if plan.mode == "no_match":
            result.success = False
            result.error = f"No matching template found. Rationale: {'; '.join(plan.rationale)}"
            return result

        # ── Step 3: Solve: Plan -> SolvedParams ──
        try:
            # Xác định family từ plan metadata
            family = ""
            solve_metadata = dict(plan.matched_metadata or {})
            solve_metadata["vcc"] = spec.vcc
            if not family:
                family = plan.matched_metadata.get("domain", {}).get("family", "")
            if not family:
                family = spec.circuit_type

            if family == "multi_stage" and plan.synthesis_plan:
                stages = plan.synthesis_plan.get("stages", [])
                topology_tokens = []
                block_to_token = {
                    "ce_block": "CE",
                    "cb_block": "CB",
                    "cc_block": "CC",
                    "cs_block": "CS",
                    "cd_block": "CD",
                    "cg_block": "CG",
                }
                for stage in stages:
                    block = str(stage.get("block", "")).strip().lower()
                    topology_tokens.append(block_to_token.get(block, "CE"))

                if topology_tokens:
                    solver_hints = dict(solve_metadata.get("solver_hints", {}))
                    solver_hints["num_stages"] = len(topology_tokens)
                    solver_hints["topology"] = "+".join(topology_tokens)
                    solve_metadata["solver_hints"] = solver_hints

            solved = self._solver.solve(
                target_gain=spec.gain,
                family=family,
                metadata=solve_metadata,
            )
            result.solved = solved
            result.stage_reached = "solve"
            logger.info(
                f"Step 3 Solve → {len(solved.values)} params, "
                f"actual_gain={solved.actual_gain}"
            )
        except Exception as e:
            result.success = False
            result.stage_reached = "solve"
            result.error = f"Solve error: {e}"
            logger.error(result.error)
            return result

        # ── Step 4: Generate: Params -> GeneratedCircuit ──
        try:
            # Lấy template file từ metadata
            template_file = self._resolve_template_file(plan.matched_template_id or "")
            force_composed = plan.mode == "composed_topology" and bool(plan.synthesis_plan)

            if force_composed:
                circuit = self._generator.generate_from_composition(
                    template_id=plan.matched_template_id or f"COMPOSED-{spec.circuit_type}",
                    composition_plan=plan.synthesis_plan,
                    solved_values=solved.values,
                    gain_formula=plan.gain_formula,
                    actual_gain=solved.actual_gain,
                    suggested_extensions=plan.suggested_extensions,
                    rationale=plan.rationale,
                )
            elif template_file:
                circuit = self._generator.generate(
                    template_id=plan.matched_template_id or "",
                    template_file=template_file,
                    solved_values=solved.values,
                    gain_formula=plan.gain_formula,
                    actual_gain=solved.actual_gain,
                    suggested_extensions=plan.suggested_extensions,
                    rationale=plan.rationale,
                    composition_plan=plan.synthesis_plan,
                )
            elif plan.synthesis_plan:
                circuit = self._generator.generate_from_composition(
                    template_id=plan.matched_template_id or f"COMPOSED-{spec.circuit_type}",
                    composition_plan=plan.synthesis_plan,
                    solved_values=solved.values,
                    gain_formula=plan.gain_formula,
                    actual_gain=solved.actual_gain,
                    suggested_extensions=plan.suggested_extensions,
                    rationale=plan.rationale,
                )
            else:
                result.success = False
                result.stage_reached = "generate"
                result.error = (
                    f"Cannot resolve template file for {plan.matched_template_id}"
                )
                return result
            result.circuit = circuit
            result.stage_reached = "generate"
            result.success = circuit.success
            if not circuit.success:
                result.error = circuit.message
            logger.info(f"Step 4 Generate → success={circuit.success}")

        except Exception as e:
            result.success = False
            result.stage_reached = "generate"
            result.error = f"Generate error: {e}"
            logger.error(result.error)
            return result

        return result



    # Liệt kê templates - trả về danh sách template đã load trong metadata repo, có thể lọc theo category
    def list_templates(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        if category:
            metas = self._repo.find_by_category(category)
        else:
            metas = list(self._repo._metadata.values())
        return [
            {
                "template_id": m["template_id"],
                "category": m.get("domain", {}).get("category", ""),
                "family": m.get("domain", {}).get("family", ""),
                "topology_tags": m.get("domain", {}).get("topology_tags", []),
            }
            for m in metas
        ]


    # Lấy metadata chi tiết của 1 template
    def get_template_detail(self, template_id: str) -> Optional[Dict[str, Any]]:
        return self._repo.get_by_template_id(template_id)

    # Trả về danh sách families hỗ trợ
    def get_supported_families(self) -> List[str]:
        families = set()
        for m in self._repo._metadata.values():
            fam = m.get("domain", {}).get("family", "")
            if fam:
                families.add(fam)
        return sorted(families)

    # Tạo gói helper để tra cứu file template (id, path) -> hỗ trợ bước Generate   
    def _resolve_template_file(self, template_id: str) -> Optional[str]:
        meta = self._repo.get_by_template_id(template_id)
        if not meta:
            return None

        ref = meta.get("physical_template_ref", {})
        file_path = ref.get("template_file", "") or ref.get("file", "")
        if file_path:
            return file_path

        # Fallback: thử tìm trong template dir
        # Template files named like: opamp_inverting_basic.json
        return None
