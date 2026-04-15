# app/domains/circuits/ai_core/topology_planner.py
""" 2: TopologyPlanner — chọn/ghép block topology
Lập kế hoạch topology (chọn block pattern) dựa trên UserSpec.

Cấp 1 (thesis):  match template gần nhất, đề xuất extension nếu cần.
Cấp 2 (tương lai): tự synthesis topology mới.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .spec_parser import UserSpec
from .metadata_repo import MetadataRepository
from .ml_topology_selector import RandomForestTopologySelector

""" lý do sử dụng thư viện
_future__ annotations: tham chiếu đến biến/thamsố/giátrị trước khi tạo xong.
logging: ghi log hoạt động của planner để theo dõi và gỡ lỗi.
dataclass, field: tạo lớp dữ liệu đơn giản để lưu trữ kế hoạch topology.
typing: cung cấp kiểu dữ liệu cho hàm và biến để tăng tính rõ ràng.

UserSpec: chứa thông tin đã parse từ yêu cầu tự nhiên của user.
MetadataRepository: cung cấp truy cập vào kho kiến thức mạch điện (templates, blocks, rules) để planner sử dụng trong quá trình lập kế hoạch.
"""

logger = logging.getLogger(__name__)


@dataclass
class TopologyPlan:
    """ Kết quả planning: danh sách block, lý do chọn topo, id template
                          thông tin match, mode, đề xuất exten,
                          công thức gain, confidence score... """

    blocks: List[str] = field(default_factory=list)
    rationale: List[str] = field(default_factory=list)
    matched_template_id: Optional[str] = None
    matched_metadata: Optional[Dict[str, Any]] = None
    mode: str = "exact_template"  # exact_template | nearest_template | no_match
    suggested_extensions: List[Dict[str, Any]] = field(default_factory=list)
    coupling_mode: str = "auto"
    synthesis_plan: Dict[str, Any] = field(default_factory=dict)
    lock_blocks: bool = False
    gain_formula: str = ""
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "blocks": self.blocks,
            "rationale": self.rationale,
            "matched_template_id": self.matched_template_id,
            "mode": self.mode,
            "suggested_extensions": self.suggested_extensions,
            "coupling_mode": self.coupling_mode,
            "synthesis_plan": self.synthesis_plan,
            "gain_formula": self.gain_formula,
            "confidence": round(self.confidence, 3),
        }


# ── Family → grammar pattern mapping ──
FAMILY_TO_GRAMMAR = {
    "instrumentation": "instrumentation_amplifier",
    "differential": "differential_amplifier",
    "non_inverting": "non_inverting_amplifier",
    "inverting": "inverting_amplifier",
    "common_emitter": "common_emitter_amplifier",
    "common_base": "common_base_amplifier",
    "common_collector": "emitter_follower",
    "common_source": "common_source_amplifier",
    "common_drain": "source_follower",
    "common_gate": "common_gate_amplifier",
    "class_a": "class_a_power_amplifier",
    "class_b": "class_b_push_pull",
    "class_ab": "class_ab_push_pull",
    "class_c": "class_c_tuned_amplifier",
    "class_d": "class_d_switching_amplifier",
    "darlington": "darlington_amplifier",
    "multi_stage": "two_stage_ce_cc",
}


class TopologyPlanner:
    """ Chọn block topology phù hợp nhất cho UserSpec.
    Thuật toán:
     1. Map circuit_type → grammar rule để lấy block pattern khởi tạo.
     2. Phân tích yêu cầu kỹ thuật -> tạo list cần.
     3. Tìm template phù hợp từ (family + pattern search)
     4. Chấm điểm từng candidate theo hàm trọng số [0, 1]:
         score = 0.35*family + 0.20*supply + 0.20*capability + 0.15*pattern + 0.10*priority
     5. Chọn mạch đạt (max_score), suy ra mode và confidence
     6. Nếu có yêu cầu mở rộng (output_buffer, ...), thêm suggested_extensions (block)
    """
    def __init__(self) -> None:
        # ML advisor là optional: nếu model chưa có thì planner vẫn chạy rule-based.
        self._ml_selector = RandomForestTopologySelector()

    def plan(self, spec: UserSpec, repo: MetadataRepository) -> TopologyPlan:
        """ pipeline: validate circuit type
                      grammar rule
                      build capabilities
                      collect & score candidates
                      check extensions
                      logging """

        repo._ensure_loaded()
        plan = TopologyPlan()
        
        if self._validate_circuit_type(spec, plan) is False:
            return plan
        
        self._resolve_grammar(spec, plan, repo)
        
        required_caps = self._build_capabilities(spec)
        
        candidates = self._collect_candidates(spec, plan, repo, required_caps)
        
        if candidates:
            self._select_best_template(spec, plan, candidates, required_caps)
        else:
            self._handle_no_candidates(spec, plan)

        self._build_synthesis_plan(spec, plan, repo)
        
        self._finalize_extensions(spec, plan, repo)
        self._log_plan(plan)
        
        return plan
    
    # 2. kiểm tra mạch hợp lệ? - không xác định đc -> no_match
    def _validate_circuit_type(self, spec: UserSpec, plan: TopologyPlan) -> bool:
        if spec.circuit_type == "unknown":
            fallback = next(
                (
                    family
                    for family in getattr(spec, "topology_candidates", [])
                    if family and family != "unknown"
                ),
                "",
            )
            if fallback:
                spec.circuit_type = fallback
                plan.rationale.append(
                    f"Fallback circuit type from functional keyword mapping: '{fallback}'"
                )
            else:
                plan.mode = "no_match"
                plan.rationale.append("Cannot identify circuit type from request")
                return False
            
        # Nâng cấp lên multi_stage nếu gain >= 100 cho TẤT CẢ các loại mạch
        is_opamp = spec.circuit_type in {"inverting", "non_inverting", "differential", "instrumentation"}
        if not is_opamp and spec.circuit_type != "multi_stage" and spec.gain is not None and spec.gain >= 100:
            plan.rationale.append(f"Gain req {spec.gain} >= 100, upgrading '{spec.circuit_type}' to 'multi_stage' to balance bandwidth, noise, and stability")
            spec.circuit_type = "multi_stage"
            spec.topology_candidates = self._merge_candidate_families(
                primary="multi_stage",
                candidates=getattr(spec, "topology_candidates", []),
            )
            
        return True
    
    # 3. resolve grammar rule từ repo (pattern block structure, gain formula)
    def _resolve_grammar(self, spec: UserSpec, plan: TopologyPlan, repo: MetadataRepository) -> None:
        # lấy thông tin từ loại mạch -> family -> default
        grammar_key = FAMILY_TO_GRAMMAR.get(spec.circuit_type, "")
        grammar_rule = repo.get_grammar_rule(grammar_key)
        
        # (!grammar) -> fallback sang family search.
        if grammar_rule:
            plan.blocks = grammar_rule.get("pattern", [])
            plan.gain_formula = grammar_rule.get("gain_formula", "")
            plan.rationale.append(f"Grammar rule '{grammar_key}' → blocks: {plan.blocks}")
        else:
            plan.rationale.append(f"No grammar rule for '{spec.circuit_type}', using family search")

        if spec.circuit_type == "multi_stage" and len(spec.requested_stage_blocks) >= 2:
            requested = spec.requested_stage_blocks
            if self._is_valid_stage_chain(requested, repo):
                plan.blocks = requested
                plan.lock_blocks = True
                plan.mode = "composed_topology"
                plan.rationale.append(f"Use requested multi-stage chain: {requested}")
            else:
                plan.rationale.append(
                    f"Requested chain {requested} is not compatible by block successor rules; fallback to grammar/template"
                )
    
    
    # 4. Thu thập mẫu từ (family, pattern) -> merge theo id (family -> pattern)
    def _collect_candidates(self, spec: UserSpec, plan: TopologyPlan, repo: MetadataRepository, required_caps: Dict[str, Any]) -> List[Dict[str, Any]]:
        family_matches: List[Dict[str, Any]] = []
        for family in self._candidate_family_order(spec):
            family_matches.extend(self._filter_by_supply(repo.find_by_family(family), spec))
        
        pattern_matches: List[Dict[str, Any]] = []
        if plan.blocks:
            pattern_matches = repo.find_by_pattern(plan.blocks, required_caps)
        
        # Hợp nhất mẫu từ family-pattern theo template_id
        candidates: List[Dict[str, Any]] = []
        seen: set[str] = set()
        
        # duyệt family matches trước (đảm bảo ưu tiên family), sau đó pattern matches, merge theo template_id để tránh trùng lặp
        for meta in [*family_matches, *pattern_matches]:
            template_id = meta.get("template_id")
            if not template_id or template_id in seen:
                continue
            seen.add(template_id)
            candidates.append(meta)
        
        return candidates
    
    # 5. tìm template tốt nhất theo hàm điểm tuyến tính, cập nhật plan với template_id, mode, confidence, rationale chi tiết
    def _select_best_template(self, spec: UserSpec, plan: TopologyPlan, candidates: List[Dict[str, Any]], required_caps: Dict[str, Any]) -> None:
        ml_context = self._ml_selector.predict_context(spec)

        scored: List[Tuple[float, Dict[str, Any], Dict[str, float]]] = [
            self._score_candidate(meta, spec, plan.blocks, required_caps, ml_context)
            for meta in candidates
        ]
        
        # Sắp xếp candidates theo điểm tổng, chọn candidate tốt nhất
        scored.sort(key=lambda item: item[0], reverse=True)
        # Lấy candidate tốt nhất và breakdown điểm để giải thích
        best_score, best, breakdown = scored[0]
        
        # Cập nhật plan với thông tin template đã chọn
        plan.matched_template_id = best.get("template_id")
        plan.matched_metadata = best
        plan.confidence = self._score_to_confidence(best_score)
        
        # Xác định mode dựa trên family match
        best_family = best.get("domain", {}).get("family")
        plan.mode = "exact_template" if best_family == spec.circuit_type else "nearest_template"
        
        # Cập nhật block từ metadata thực tế
        fs = best.get("functional_structure", {})
        actual_blocks = [b["type"] for b in fs.get("blocks", []) if isinstance(b, dict) and "type" in b]
        if actual_blocks and not plan.lock_blocks:
            plan.blocks = actual_blocks
        elif actual_blocks and plan.lock_blocks and actual_blocks != plan.blocks:
            plan.mode = "composed_topology"
            plan.rationale.append(
                f"Template blocks {actual_blocks} differ from requested chain {plan.blocks}; keep composed chain"
            )

        # Cập nhật gain formula nếu có trong metadata
        plan.gain_formula = fs.get("total_gain_formula", plan.gain_formula)
        plan.rationale.append(
            "Best candidate by weighted score "
            f"{best_score:.3f} (family={breakdown['family']:.2f}, "
            f"supply={breakdown['supply']:.2f}, cap={breakdown['capability']:.2f}, "
            f"pattern={breakdown['pattern']:.2f}, priority={breakdown['priority']:.2f}, "
            f"ml={breakdown['ml']:.2f})"
        )
        # match template id và family để giải thích lý do chọn template đó
        plan.rationale.append(f"Matched template: {plan.matched_template_id} (family={best_family})")
        
    # 6. xử lý khi không tìm được mẫu phù hợp
    def _handle_no_candidates(self, spec: UserSpec, plan: TopologyPlan) -> None:
        if spec.circuit_type == "multi_stage" and plan.blocks:
            plan.mode = "composed_topology"
            plan.confidence = 0.55
            plan.rationale.append(
                "No fixed template found; fallback to composed multi-stage synthesis from block grammar"
            )
            return

        plan.mode = "no_match"
        plan.confidence = 0.0
        if plan.blocks:
            plan.rationale.append("No matching template found from family/pattern candidates")
        else:
            plan.rationale.append("No blocks resolved and no pattern available")

    def _build_synthesis_plan(self, spec: UserSpec, plan: TopologyPlan, repo: MetadataRepository) -> None:
        if len(plan.blocks) < 2:
            return

        is_multi_stage = spec.circuit_type == "multi_stage" or len(plan.blocks) > 1
        if not is_multi_stage:
            return

        coupling_mode = self._select_coupling_mode(spec, plan, repo)
        coupling_rule = repo.get_coupling_rule(coupling_mode)
        if not coupling_rule:
            coupling_mode = "capacitor"
            coupling_rule = repo.get_coupling_rule(coupling_mode)

        if not coupling_rule:
            plan.rationale.append("Coupling rules unavailable; skipped synthesis plan")
            return

        stages = [
            {"stage_id": f"stage{idx + 1}", "block": block}
            for idx, block in enumerate(plan.blocks)
        ]

        interstage_links: List[Dict[str, Any]] = []
        coupling_block = coupling_rule.get("intermediary_block", "ac_coupling_block")
        prefix = coupling_rule.get("default_component_prefix", "CP")
        default_params = coupling_rule.get("default_parameters", {})

        for idx in range(len(stages) - 1):
            src = stages[idx]
            dst = stages[idx + 1]
            interstage_links.append(
                {
                    "link_id": f"{src['stage_id']}_to_{dst['stage_id']}",
                    "from_stage": src["stage_id"],
                    "to_stage": dst["stage_id"],
                    "from_block": src["block"],
                    "to_block": dst["block"],
                    "coupling_mode": coupling_mode,
                    "coupling_block": coupling_block,
                    "coupling_component_ref": f"{prefix}{idx + 1}",
                    "parameters": default_params,
                }
            )

        required_blocks = list(plan.blocks)
        required_blocks.extend([link["coupling_block"] for link in interstage_links])

        plan.coupling_mode = coupling_mode
        plan.synthesis_plan = {
            "family": spec.circuit_type,
            "composition_type": "multi_stage",
            "target_gain": spec.gain,
            "stages": stages,
            "interstage_links": interstage_links,
            "required_blocks": required_blocks,
            "constraints": coupling_rule.get("constraints", []),
        }
        plan.rationale.append(
            f"Synthesis plan generated with coupling='{coupling_mode}' for {len(stages)} stages"
        )

    def _select_coupling_mode(self, spec: UserSpec, plan: TopologyPlan, repo: MetadataRepository) -> str:
        supported_modes = set(repo.list_coupling_modes())
        if not supported_modes:
            return "capacitor"

        preferred = (spec.coupling_preference or "auto").strip().lower()
        if preferred != "auto" and preferred in supported_modes:
            return preferred

        if "ac_coupled" in set(spec.extra_requirements) and "capacitor" in supported_modes:
            return "capacitor"

        if preferred == "auto" and plan.matched_metadata:
            hints = plan.matched_metadata.get("planner_hints", {})
            supported_hint = hints.get("coupling_modes_supported", [])
            if isinstance(supported_hint, list):
                for mode in supported_hint:
                    mode_text = str(mode).strip().lower()
                    if mode_text in supported_modes:
                        return mode_text

        return "capacitor" if "capacitor" in supported_modes else sorted(supported_modes)[0]
    
    # 7. cần extension block không? (dựa trên spec + rules), thêm vào plan nếu có
    def _finalize_extensions(self, spec: UserSpec, plan: TopologyPlan, repo: MetadataRepository) -> None:
        extensions = self._check_extensions(spec, plan, repo)
        
        if extensions:
            plan.suggested_extensions = extensions
            plan.rationale.append(f"Suggested extensions: {[e['extension_block'] for e in extensions]}")

    # 8. log thông tin tổng kết của plan
    def _log_plan(self, plan: TopologyPlan) -> None:
        logger.info(f"TopologyPlan: mode={plan.mode}, template={plan.matched_template_id}, blocks={plan.blocks}, confidence={plan.confidence:.2f}")
        
    
    
    # Xây dựng danh sách capabilities từ yêu cầu
    def _build_capabilities(self, spec: UserSpec) -> List[str]:
        caps = []
        if spec.gain and spec.gain > 1:
            caps.append("voltage_gain")
        if spec.high_cmr:
            caps.append("high_cmrr")
        if spec.input_mode == "differential":
            caps.append("differential_input")
        if spec.output_buffer:
            caps.append("low_output_impedance")
        if spec.power_output:
            caps.append("power_amplification")
        caps.extend(spec.extra_requirements)
        return caps



    """ Tính điểm mẫu theo trọng số tuyến tính (linear weighted scoring).
    Thành phần: family match, supply compatibility, capability coverage, pattern similarity, priority hint.
    Trả về tổng điểm, metadata gốc, và breakdown chi tiết để giải thích.
    """
    def _score_candidate(
        self,
        meta: Dict[str, Any],
        spec: UserSpec,
        planned_blocks: List[str],
        required_caps: List[str],
        ml_context: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> Tuple[float, Dict[str, Any], Dict[str, float]]:
        domain = meta.get("domain", {})
        hints = meta.get("planner_hints", {})
        fs = meta.get("functional_structure", {})

        family_score = self._compute_family_score(domain, spec)
        supply_score = self._compute_supply_score(domain, spec)
        capability_score = self._compute_capability_score(hints, required_caps)
        pattern_score = self._compute_pattern_score(fs, planned_blocks)
        priority_score = self._compute_priority_score(hints)
        ml_score = self._ml_selector.score_candidate(meta, ml_context)
        ml_weighted_contribution = 0.15 * ml_score

        logger.debug(
            "RF score debug | template=%s raw_ml=%.4f weighted_contribution=%.4f",
            str(meta.get("template_id", "")),
            ml_score,
            ml_weighted_contribution,
        )

        total_score = self._combine_weighted_score(
            family=family_score,
            supply=supply_score,
            capability=capability_score,
            pattern=pattern_score,
            priority=priority_score,
            ml=ml_score,
        )

        breakdown = {
            "family": family_score,
            "supply": supply_score,
            "capability": capability_score,
            "pattern": pattern_score,
            "priority": priority_score,
            "ml": ml_score,
            "ml_weighted": ml_weighted_contribution,
        }
        return total_score, meta, breakdown
    
    # Tính điểm family: 1 - trùng, 0 - khác
    def _compute_family_score(self, domain: Dict[str, Any], spec: UserSpec) -> float:
        family = str(domain.get("family") or "")
        if family == spec.circuit_type:
            return 1.0

        ranked = self._candidate_family_order(spec)
        if family in ranked:
            idx = ranked.index(family)
            return max(0.45, 0.88 - 0.12 * idx)
        return 0.0

    @staticmethod
    def _merge_candidate_families(primary: str, candidates: List[str]) -> List[str]:
        ordered: List[str] = []
        if primary and primary != "unknown":
            ordered.append(primary)
        for family in candidates:
            if family and family != "unknown" and family not in ordered:
                ordered.append(family)
        return ordered

    def _candidate_family_order(self, spec: UserSpec) -> List[str]:
        return self._merge_candidate_families(
            primary=spec.circuit_type,
            candidates=getattr(spec, "topology_candidates", []),
        )
    
    # Tính điểm supply: 1 - phù hợp, 0 - không phù hợp, 0.5 - không rõ
    def _compute_supply_score(self, domain: Dict[str, Any], spec: UserSpec) -> float:
        if spec.supply_mode == "auto":
            return 1.0
        
        tags = domain.get("topology_tags", [])
        
        if spec.supply_mode == "single_supply":
            return 1.0 if "single_supply" in tags else 0.0
        
        elif spec.supply_mode == "dual_supply":
            if "dual_supply" in tags:
                return 1.0
            elif "single_supply" in tags:
                return 0.0
            else:
                return 0.5
        
        return 1.0
    
    # Tính mức độ bao phủ capability: tỷ lệ capabilities yêu cầu có trong metadata
    def _compute_capability_score(self, hints: Dict[str, Any], required_caps: List[str]) -> float:
        if not required_caps:
            return 1.0

        req = set(required_caps)
        meta_caps = set(hints.get("required_capabilities", []))
        
        return len(req & meta_caps) / len(req)
        
    # Tính mức độ overlap: block pattern (template) - block pattern (grammar)
    def _compute_pattern_score(self, function_structure: Dict[str, Any], planned_blocks: List[str]) -> float:
        ordered = function_structure.get("pattern_signature", {}).get("ordered_block_types", [])

        return self._list_overlap_score(planned_blocks, ordered)
    
    # Lấy priority score từ metadata và chuẩn hóa về [0, 1] nếu ko thì 0.5 (default)
    def _compute_priority_score(self, hints: Dict[str, Any]) -> float:
        priority_score = float(hints.get("priority_score", 0.5))
        return max(0.0, min(priority_score, 1.0))
    
    # Kết hợp các thành phần điểm với trọng số để tính tổng điểm cuối cùng
    def _combine_weighted_score(
        self,
        family: float,
        supply: float,
        capability: float,
        pattern: float,
        priority: float,
        ml: float,
    ) -> float:
        return (
            0.30 * family
            + 0.18 * supply
            + 0.17 * capability
            + 0.10 * pattern
            + 0.10 * priority
            + 0.15 * ml
        )



    
    @staticmethod
    def _score_to_confidence(score: float) -> float:
        """ Chuyển đổi score [0 1] sang confidence [0.3 0.98] - tránh confidence quá thấp (0.0) hoặc quá cao (1.0). Đảm bảo kết quả luôn nằm trong khoảng hợp lý."""
        s = max(0.0, min(score, 1.0))
        return 0.3 + 0.68 * s

    def _is_valid_stage_chain(self, blocks: List[str], repo: MetadataRepository) -> bool:
        if len(blocks) < 2:
            return False

        for idx in range(len(blocks) - 1):
            current_block = blocks[idx]
            next_block = blocks[idx + 1]
            block_def = repo.get_block_definition(current_block) or {}
            successors = block_def.get("compatible_successors", [])
            if "any" in successors:
                continue
            if next_block not in successors:
                return False
        return True

    @staticmethod
    def _list_overlap_score(list_a: List[str], list_b: List[str]) -> float:
        """ Tính mức độ giống nhau giữa hai danh sách block types (Jaccard) để rate pattern match:
        - Kết quả = số phần tử chung / tổng số phần tử khác nhau.
        - Nếu hai list giống nhau hoàn toàn: score = 1.0
        - Nếu không có phần tử chung: score = 0.0
        """
        if not list_a or not list_b:    # rỗng
            return 0.0
        set_a = set(list_a)
        set_b = set(list_b)
        inter = set_a & set_b
        if not inter:                   # ko một phần tử chung
            return 0.0
        union = set_a | set_b
        return len(inter) / len(union)

    def _filter_by_supply(self, candidates: List[Dict], spec: UserSpec) -> List[Dict]:
        """
        Lọc danh sách template theo chế độ nguồn (supply mode) mà user yêu cầu:
        - Nếu user chọn single_supply: chỉ lấy các template có tag 'single_supply'.
        - Nếu dual_supply: ưu tiên template có tag 'dual_supply', hoặc không có tag 'single_supply'.
        - Nếu không lọc được thì trả lại toàn bộ danh sách ban đầu.
        """
        # mode: auto - không lọc
        if spec.supply_mode == "auto":
            return candidates
        
        filtered = [] # lưu temp lọc
        for meta in candidates:
            tags = meta.get("domain", {}).get("topology_tags", [])
            if spec.supply_mode == "single_supply" and "single_supply" in tags:
                filtered.append(meta)
            elif spec.supply_mode == "dual_supply" and "dual_supply" in tags:
                filtered.append(meta)
            elif spec.supply_mode == "dual_supply" and "single_supply" not in tags:
                # Nếu không gắn tag single thì mặc định là dual
                filtered.append(meta)
        return filtered if filtered else candidates


    # Kiểm tra và đề xuất extension blocks dựa trên spec + grammar rules
    def _check_extensions(self, spec: UserSpec, plan: TopologyPlan, repo: MetadataRepository) -> List[Dict[str, Any]]:
        """ Đề xuất extension blocks cần thêm vào topology:
        - Level 1: output buffer, power stage (từ spec trực tiếp)
        - Level 2/3: protection, compensation, feedback (từ grammar rules)
        Tránh đề xuất block đã có trong plan hoặc đã đề xuất trước đó.
        """
        extensions: List[Dict[str, Any]] = []
        existing_blocks = set(plan.blocks)

        def _already_suggested(ext_block: str) -> bool:
            """Kiểm tra block đã có trong plan hoặc đã được đề xuất chưa."""
            return ext_block in existing_blocks or any(e["extension_block"] == ext_block for e in extensions)

        # 1. Output buffer (CC/CD) nếu user yêu cầu giảm Zout
        if spec.output_buffer and plan.blocks:
            last_block = plan.blocks[-1]
            if last_block not in ("cc_block", "cd_block"):
                ext_block = "cd_block" if spec.device_preference == "mosfet" else "cc_block"
                label = "CD (source follower)" if ext_block == "cd_block" else "CC (emitter follower)"
                if not _already_suggested(ext_block):
                    extensions.append({
                        "extension_block": ext_block,
                        "attach_to": f"{last_block}:OUT",
                        "reason": "User yêu cầu output buffer để giảm Zout",
                        "level": "level_1_suggest",
                        "rationale": f"Thêm {label} sau {last_block} để giảm trở kháng đầu ra, tăng khả năng kéo tải.",
                    })
                    plan.rationale.append(f"Extension: {ext_block} → giảm Zout cho tầng cuối {last_block}")

        # 2. Power stage nếu spec yêu cầu khuếch đại công suất
        if spec.power_output and plan.blocks:
            last_block = plan.blocks[-1]
            if last_block not in ("class_ab_block", "class_b_block"):
                ext_block = "class_ab_block"
                if not _already_suggested(ext_block):
                    extensions.append({
                        "extension_block": ext_block,
                        "attach_to": f"{last_block}:OUT",
                        "reason": "User yêu cầu khuếch đại công suất",
                        "level": "level_1_suggest",
                        "rationale": f"Thêm tầng Class-AB sau {last_block} để đáp ứng yêu cầu công suất ra.",
                    })
                    plan.rationale.append(f"Extension: {ext_block} → tầng công suất cho {last_block}")

        # 3. Extension rules từ grammar repo — hỗ trợ level 1/2/3
        SUPPORTED_LEVELS = ("level_1_suggest", "level_2_advanced", "level_3_expert")
        ext_rules = repo.get_extension_rules()
        for rule in ext_rules:
            base = rule.get("base_pattern", [])
            rule_level = rule.get("level", "")

            if plan.blocks == base and rule_level in SUPPORTED_LEVELS:
                ext_block = rule.get("extension_block", "")
                if ext_block and not _already_suggested(ext_block):
                    extensions.append({
                        "extension_block": ext_block,
                        "attach_to": rule.get("attach_to", ""),
                        "reason": rule.get("reason", ""),
                        "level": rule_level,
                        "rationale": rule.get("rationale", f"Grammar rule đề xuất thêm {ext_block} cho pattern {base}."),
                    })
                    plan.rationale.append(f"Extension [{rule_level}]: {ext_block} → {rule.get('reason', '')}")

        return extensions
