# app/domains/circuits/ai_core/ai_core.py
""" AI Core - Main Orchestrator
Điều phối 4 bước:
    Parse (yêu cầu) → Plan(chọn&ghép) → Solve (giải mã) → Generate
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

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
            solve_metadata = plan.matched_metadata
            if plan.matched_metadata:
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
                    solve_metadata = dict(plan.matched_metadata or {})
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
