# .\thesis\electronic-chatbot\apps\api\app\application\ai\nlu_service.py
"""Natural Language Understanding (NLU) Service.

Phân tích ý definition từ user input thành CircuitIntent domain object.

Luồng xử lý NLU:
 1. Rule-based parsing: regex + spec parser (nhanh, deterministic)
 2. LLM parsing: LLM Router theo mode Air/Pro (chính xác hơn, slow)
 3. Hợp nhất: merge rule-based + LLM kết quả
 4. Fallback: rule-based khi LLM không khả dụng hoặc fail

Module này chịu trách nhiệm:
 - Nhận user text → CircuitIntent entity
 - Phát hiện missing info, hỏi clarification
 - Bảo đảm intent đủ để sinh mạch

Nguyên tắc:
 - Adapter pattern: tầng application, phụ thuộc spec parser + LLM Router
 - Rule-based first: nhanh, consistent, không timeout
 - LLM enhance: độ chính xác cao hơn nếu có
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.application.ai.llm_router import LLMMode

# ====== Lý do sử dụng thư viện ======
# __future__ annotations: forward reference cho CircuitIntent (type hinting)
# logging: ghi log analyze flow, detect missing info
# re: regex parse pattern từ user input (e.g., "gain 50", "12V")
# dataclass + field: định nghĩa CircuitIntent, EditOperation value objects
# typing + TYPE_CHECKING: type safe, tránh circular import LLMMode

logger = logging.getLogger(__name__)

@dataclass
class EditOperation:
    # Thao tác (thêm/xóa/thay đổi linh kiện/kết nối)
    action: str = ""        # "add_component" | "remove_component" | "replace_component" | "change_value" | "change_connection"
    target: str = ""        # component id hoặc net name: "R1", "C2", "Q1"
    params: Dict[str, Any] = field(default_factory=dict)  # {"type": "resistor", "value": 10000} hoặc {"new_value": 4700}

    def to_dict(self) -> dict:
        return {"action": self.action, "target": self.target, "params": self.params}


@dataclass
class CircuitIntent:
    # phân tích ý định
    intent_type: str = "create"     # "create"(default) | "modify" | "validate" | "explain" | "optimize" | "compare"

    # thuộc tính cơ bản
    circuit_type: str = ""
    topology: str = ""
    gain_target: Optional[float] = None
    vcc: Optional[float] = None
    frequency: Optional[float] = None
    input_channels: int = 1
    channel_inputs: Dict[str, Dict[str, Optional[float]]] = field(default_factory=dict)
    voltage_range: Dict[str, Optional[float]] = field(default_factory=dict)
    input_mode: str = "single_ended"
    high_cmr: bool = False                  # common-mode rejection ratio
    output_buffer: bool = False
    power_output: bool = False
    supply_mode: str = "auto"
    device_preference: str = "auto"
    extra_requirements: List[str] = field(default_factory=list)

    # thao tác sửa chữa (dùng cho modify)
    edit_operations: List[EditOperation] = field(default_factory=list)
    target_scope: str = "entire_circuit"    # "input_stage" | "output_stage" | "bias_network" | "feedback_loop" | "entire_circuit"
    requested_actions: List[str] = field(default_factory=list)  # multi-intent: ["create", "explain", ...]
    explain_detail_level: str = "basic"  # "basic" | "detailed"
    explain_focus_components: List[str] = field(default_factory=list)

    # thông tin bổ sung (metadata)
    hard_constraints: Dict[str, Any] = field(default_factory=dict)   # bắt buộc: {"vcc_max": 15, "gain_min": 10}
    soft_preferences: List[str] = field(default_factory=list)        # mong muốn: ["low_noise", "small_footprint"]

    # độ tin cậy và nguồn gốc thông tin
    confidence: float = 0.0     # giá trị tin cậy
    source: str = "rule_based"  # "rule_based" | "llm" | "symbolic"
    raw_text: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "intent_type": self.intent_type,
            "circuit_type": self.circuit_type,
            "topology": self.topology,
            "gain_target": self.gain_target,
            "vcc": self.vcc,
            "frequency": self.frequency,
            "input_channels": self.input_channels,
            "channel_inputs": self.channel_inputs,
            "voltage_range": self.voltage_range,
            "input_mode": self.input_mode,
            "high_cmr": self.high_cmr,
            "output_buffer": self.output_buffer,
            "power_output": self.power_output,
            "supply_mode": self.supply_mode,
            "device_preference": self.device_preference,
            "extra_requirements": self.extra_requirements,
            "edit_operations": [op.to_dict() for op in self.edit_operations],
            "target_scope": self.target_scope,
            "requested_actions": self.requested_actions,
            "explain_detail_level": self.explain_detail_level,
            "explain_focus_components": self.explain_focus_components,
            "hard_constraints": self.hard_constraints,
            "soft_preferences": self.soft_preferences,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "warnings": self.warnings,
        }

# Xác định cấu trúc mạch - Template family mapping
CIRCUIT_TYPE_MAP = {
    "ce": "common_emitter",
    "common_emitter": "common_emitter",
    "cb": "common_base",
    "common_base": "common_base",
    "cc": "common_collector",
    "common_collector": "common_collector",
    "emitter_follower": "common_collector",
    "cs": "common_source",
    "common_source": "common_source",
    "cd": "common_drain",
    "common_drain": "common_drain",
    "source_follower": "common_drain",
    "cg": "common_gate",
    "common_gate": "common_gate",
    "inverting": "inverting", "inv amp": "inverting", "opamp đảo": "inverting", "mạch đảo": "inverting", "gain âm": "inverting",
    "non inverting": "non_inverting", "non-inverting": "non_inverting", "không đảo": "non_inverting", "đảo pha": "inverting", "đảo": "inverting",
    "differential": "differential", "diff amp": "differential", "difference amp": "differential", "subtractor": "differential", "vi sai": "differential",
    "instrumentation": "instrumentation", "instrument amp": "instrumentation", "in-amp": "instrumentation", "inamp": "instrumentation", "precision amp": "instrumentation", "khuếch đại đo lường": "instrumentation",
    "class_a": "class_a", "a_class": "class_a", "class_a_amp": "class_a", "khuếch_đại_lớp_a": "class_a", "class_A": "class_a",
    "class_b": "class_b", "b_class": "class_b", "class_b_amp": "class_b", "khuếch_đại_lớp_b": "class_b", "class_B": "class_b",
    "class_ab": "class_ab", "ab_class": "class_ab", "class_ab_amp": "class_ab", "khuếch_đại_lớp_ab": "class_ab", "class_AB": "class_ab",
    "class_c": "class_c", "c_class": "class_c", "class_c_amp": "class_c", "khuếch_đại_lớp_c": "class_c", "class_C": "class_c",
    "class_d": "class_d", "d_class": "class_d", "class_d_amp": "class_d", "khuếch_đại_lớp_d": "class_d", "class_D": "class_d",
    "darlington": "darlington", "cặp_darlington": "darlington", "darlington_pair": "darlington", "transistor_kép": "darlington",
    "multi_stage": "multi_stage", "mul_stage": "multi_stage", "cascade": "multi_stage",
}

# nhận diện keywords (VN+ENG) cho từng loại mạch-circuit type trong spec_parser
CIRCUIT_TYPE_KEYWORDS = {
    "instrumentation": [
        r"instrumentation", r"measurement\s*amp", r"3[\s-]*op[\s-]*amp", r"in-amp", r"inamp",
        r"instrument\s*amp", r"instrument\s*amplifier", r"precision\s*amp",
        r"khuếch\s*đại\s*đo\s*lường", r"amp\s*đo\s*lường", r"amp\s*cảm\s*biến",
        # MỚI
        r"\bina\b", r"bridge[\s_-]*amp", r"strain[\s_-]*gauge\s*amp",
        r"khuếch\s*đại\s*chính\s*xác", r"mạch\s*ina", r"wheatstone\s*amp",
    ],
    "differential": [
        r"differential", r"difference\s*amp", r"subtractor",
        r"diff\s*amp", r"amp\s*vi\s*sai", r"khuếch\s*đại\s*vi\s*sai",
        r"mạch\s*vi\s*sai", r"mạch\s*so\s*hiệu",
        # MỚI
        r"long[\s-]*tail[\s_-]*pair", r"ltp\b", r"emitter[\s-]*coupled\s*pair",
        r"diff[\s_-]*pair", r"cặp\s*vi\s*sai", r"mạch\s*hiệu",
    ],
    "non_inverting": [
        r"non[\s_-]*inverting", r"non_inverting", r"không\s*đảo",
        r"noninv", r"opamp\s*không\s*đảo", r"mạch\s*không\s*đảo", r"gain\s*dương",
        # MỚI
        r"thuận\s*pha", r"đồng\s*pha", r"khuếch\s*đại\s*thuận\s*pha",
        r"voltage\s*follower(?!\s*bjt)(?!\s*mosfet)",
        r"unity[\s_-]*gain", r"in[\s-]*phase\s*amp",
    ],
    "inverting": [
        r"inverting(?!\s*non)", r"đảo\s*pha",
        r"inv\s*amp", r"opamp\s*đảo", r"mạch\s*đảo",
        r"khuếch\s*đại\s*đảo", r"gain\s*âm",
        # MỚI
        r"nghịch\s*pha", r"khuếch\s*đại\s*nghịch\s*pha",
        r"phase[\s_-]*inverter", r"virtual[\s_-]*ground\s*amp", r"inv\s*amplifier",
    ],
    "common_emitter": [
        r"common[\s_-]*emitter", r"\bce\b", r"emitter\s*chung", r"common_emitter",
        r"bjt\s*ce", r"tầng\s*ce", r"mạch\s*ce", r"khuếch\s*đại\s*ce",
        # MỚI
        r"mạch\s*transistor", r"e\s*chung", r"mắc\s*kiểu\s*e\s*chung",
        r"cực\s*phát\s*chung", r"grounded[\s_-]*emitter",
        r"ce\s*amplifier", r"voltage\s*amp\s*bjt",
    ],
    "common_base": [
        r"common[\s_-]*base", r"\bcb\b", r"base\s*chung", r"common_base",
        r"bjt\s*cb", r"tầng\s*cb", r"khuếch\s*đại\s*cb",
        # MỚI
        r"b\s*chung", r"mạch\s*b\s*chung", r"cực\s*nền\s*chung",
        r"cực\s*gốc\s*chung", r"grounded[\s_-]*base", r"cb\s*amplifier",
    ],
    "common_collector": [
        r"common[\s_-]*collector", r"\bcc\b", r"emitter\s*follower",
        r"collector\s*chung", r"common_collector",
        r"buffer\s*bjt", r"bjt\s*follower", r"voltage\s*follower\s*bjt", r"tầng\s*đệm",
        # MỚI
        r"c\s*chung", r"mạch\s*c\s*chung", r"cực\s*thu\s*chung",
        r"cực\s*góp\s*chung", r"mạch\s*lặp\s*emitter",
        r"grounded[\s_-]*collector", r"cc\s*amplifier",
    ],
    "common_source": [
        r"common[\s_-]*source", r"\bcs\b", r"source\s*chung", r"common_source",
        r"mosfet\s*cs", r"tầng\s*cs", r"khuếch\s*đại\s*cs",
        # MỚI
        r"s\s*chung", r"mạch\s*s\s*chung", r"cực\s*nguồn\s*chung",
        r"grounded[\s_-]*source", r"cs\s*amplifier", r"fet\s*amp",
    ],
    "common_drain": [
        r"common[\s_-]*drain", r"\bcd\b", r"source\s*follower",
        r"drain\s*chung", r"common_drain",
        r"mosfet\s*follower", r"voltage\s*follower\s*mosfet",
        r"tầng\s*cd", r"mạch\s*đệm\s*mosfet",
        # MỚI
        r"d\s*chung", r"mạch\s*d\s*chung", r"cực\s*máng\s*chung",
        r"mạch\s*lặp\s*source", r"grounded[\s_-]*drain", r"cd\s*amplifier",
    ],
    "common_gate": [
        r"common[\s_-]*gate", r"\bcg\b", r"gate\s*chung", r"common_gate",
        r"mosfet\s*cg", r"tầng\s*cg", r"khuếch\s*đại\s*cg",
        # MỚI
        r"g\s*chung", r"mạch\s*g\s*chung", r"cực\s*cổng\s*chung",
        r"grounded[\s_-]*gate", r"cg\s*amplifier",
    ],
    "class_ab": [
        r"class[\s_-]*ab", r"lớp\s*ab",
        r"class\s*a\s*b", r"khuếch\s*đại\s*lớp\s*ab",
        # MỚI
        r"chế\s*độ\s*ab", r"push[\s-]*pull[\s_-]*ab",
        r"complementary[\s_-]*ab", r"khuếch\s*đại\s*bù",
    ],
    "class_a": [
        r"class[\s_-]*a(?![b-z])", r"lớp\s*a\b",
        r"class\s*a\s*amp", r"khuếch\s*đại\s*lớp\s*a",
        # MỚI
        r"chế\s*độ\s*a\b", r"single[\s-]*ended\s*amp",
        r"mạch\s*đơn\s*cực", r"toàn\s*kỳ",
    ],
    "class_b": [
        r"class[\s_-]*b(?![a-z])", r"lớp\s*b\b",
        r"khuếch\s*đại\s*lớp\s*b",
        # MỚI
        r"chế\s*độ\s*b\b", r"push[\s-]*pull(?!\s*ab)",
        r"bán\s*kỳ", r"crossover\s*amp", r"complementary[\s_-]*amp",
    ],
    "class_c": [
        r"class[\s_-]*c(?![a-z])", r"lớp\s*c\b", r"tuned\s*amp",
        r"rf\s*amp", r"khuếch\s*đại\s*rf",
        # MỚI
        r"chế\s*độ\s*c\b", r"resonant[\s_-]*amp",
        r"tank[\s_-]*circuit", r"khuếch\s*đại\s*cộng\s*hưởng",
        r"narrow[\s-]*band\s*amp",
    ],
    "class_d": [
        r"class[\s_-]*d(?![a-z])", r"lớp\s*d\b", r"switching\s*amp",
        r"pwm\s*amp", r"digital\s*amp", r"khuếch\s*đại\s*xung",
        # MỚI
        r"chế\s*độ\s*d\b", r"h[\s-]*bridge\s*amp",
        r"khuếch\s*đại\s*chuyển\s*mạch", r"khuếch\s*đại\s*số",
        r"full[\s-]*bridge\s*amp",
    ],
    "darlington": [
        r"darlington",
        r"cặp\s*darlington", r"darlington\s*pair", r"transistor\s*kép",
        # MỚI
        r"super[\s-]*beta", r"compound[\s_-]*transistor",
        r"sziklai", r"transistor\s*hợp",
        r"bjt\s*kép", r"tầng\s*darlington",
    ],
    "multi_stage": [
        r"multi[\s_-]*stage", r"two[\s-]*stage", r"nhiều\s*tầng",
        r"2\s*tầng", r"cascade", r"multi_stage",
        r"3\s*tầng", r"three[\s-]*stage", r"khuếch\s*đại\s*nhiều\s*tầng",
        # MỚI
        r"ghép\s*tầng", r"khuếch\s*đại\s*ghép",
        r"rc[\s-]*coupled", r"dc[\s-]*coupled",
        r"direct[\s-]*coupled", r"capacitor[\s-]*coupled",
        r"pre[\s-]*amp", r"tiền\s*khuếch\s*đại",
    ],
}



class NLUService:
    # Nhận diện intent (thuộc tính + loại mạch)
    _MODIFY_PATTERNS: List[str] = [
        r"\bthay\s*đổi\b", r"\bchỉnh\s*sửa\b", r"\bcập\s*nhật\b", r"\bsửa\b",
        r"\bmodify\b", r"\bchange\b", r"\bupdate\b", r"\bedit\b", r"\balter\b",
        r"\bđổi\s*giá\s*trị\b", r"\bthay\s*giá\s*trị\b",
    ]
    _ADD_PATTERNS: List[str] = [
        r"\bthêm\b", r"\bbổ\s*sung\b", r"\btạo\s*thêm\b", r"\bgắn\s*thêm\b",
        r"\badd\b", r"\binsert\b", r"\bappend\b",
        r"\bthêm\s*vào\b", r"\bthêm\s*linh\s*kiện\b",
    ]
    _REMOVE_PATTERNS: List[str] = [
        r"\bxóa\b", r"\bloại\s*bỏ\b", r"\bbỏ\b", r"\bgỡ\b", r"\bgỡ\s*bỏ\b",
        r"\bremove\b", r"\bdelete\b", r"\bdrop\b",
        r"\bgiảm\s*bớt\b", r"\bbớt\b",
    ]
    _VALIDATE_PATTERNS: List[str] = [
        r"\bkiểm\s*tra\b", r"\bvalidate\b", r"\bcheck\b", r"\bverify\b",
        r"\bxác\s*nhận\b", r"\brà\s*soát\b",
    ]
    _EXPLAIN_PATTERNS: List[str] = [
        r"\bgiải\s*thích\b", r"\bexplain\b", r"\btại\s*sao\b", r"\bwhy\b",
        r"\bhow\s*does\b", r"\bhoạt\s*động\s*thế\s*nào\b",
        r"\bchức\s*năng\b", r"\bphân\s*tích\b", r"\bmô\s*tả\b",
        r"\bchi\s*tiết\b", r"\bnguyên\s*lý\b",
    ]
    _OPTIMIZE_PATTERNS: List[str] = [
        r"\btối\s*ưu\b", r"\boptimize\b", r"\bcải\s*thiện\b", r"enhanced",
        r"\btối\s*ưu\s*cho\b", r"\btối\s*ưu\s*lại\b", r"\btối\s*ưu\s*hiệu\s*suất\b",
        r"\bnâng\s*cấp\b", r"\bhiệu\s*suất\b", r"\bperformance\b",
    ]
    _COMPARE_PATTERNS: List[str] = [
        r"\bso\s*sánh\b", r"\bcompare\b", r"\bđối\s*chiếu\b", r"\bđánh\s*giá\b",
    ]
    _SCOPE_PATTERNS: Dict[str, List[str]] = {
        "input_stage": [r"\btầng\s*vào\b", r"\binput\s*stage\b", r"\bđầu\s*vào\b"],
        "output_stage": [r"\btầng\s*ra\b", r"\boutput\s*stage\b", r"\bđầu\s*ra\b"],
        "bias_network": [r"\bmạng\s*phân\s*cực\b", r"\bbias\b", r"\bphân\s*cực\b"],
        "feedback_loop": [r"\bhồi\s*tiếp\b", r"\bfeedback\b"],
    }

    def __init__(self) -> None:
        self._router = None
        self._init_router()

    def _init_router(self) -> None:
        # Khởi tạo LLM router dùng chung theo mode Air/Pro.
        try:
            from app.application.ai.llm_router import get_router, LLMRole
            router = get_router()
            if router.is_available(LLMRole.GENERAL):
                self._router = router
                logger.info("NLU: Tiến trình điều phối sắn sàng.")
            else:
                logger.info("NLU: Chưa cấu hình API Key, Sử dụng cơ chế base.")
        except Exception as e:
            logger.warning(f"NLU: Khởi tạo thất bại: {e}")

    def understand(self, user_text: str, mode: Optional["LLMMode"] = None) -> CircuitIntent:
        # Phân tích yêu cầu user theo 2 nhánh: rule-based và LLM, sau đó hợp nhất.
        rule_intent = self._rule_based_parse(user_text)

        # Nhánh LLM theo mode đang chọn
        if self._router:
            try:
                llm_intent = self._llm_extract(user_text, mode=mode)
                # kiểm tra mức độ tin cậy -> cao hơn thì merge
                if llm_intent and llm_intent.confidence > rule_intent.confidence:
                    merged = self._merge_intents(rule_intent, llm_intent)
                    merged.source = "merged"
                    return merged
        
            except Exception as e:
                logger.warning(f"NLU: Khởi tạo LLM service thất bại, sử dụng base: {e}")
                rule_intent.warnings.append(f"LLM fallback: {e}")

        return rule_intent
    
    #  Rule-based parser
    def _rule_based_parse(self, text: str) -> CircuitIntent:
        # Phân tích bằng regex - tương tự SpecParser.
        intent = CircuitIntent(raw_text=text)
        lower = text.lower().strip()

        # Nhận diện intent_type trước
        self._parse_intent_type(lower, intent)

        # refactor -> small method
        self._parse_circuit_type(lower, intent)
        self._parse_gain(lower, intent)
        self._parse_vcc(lower, intent)
        self._parse_frequency(lower, intent)
        self._parse_input_channels(lower, intent)
        self._parse_channel_inputs(lower, intent)
        self._parse_voltage_range(lower, intent)
        self._parse_flags(lower, intent)
        self._parse_input_mode(lower, intent)
        self._parse_supply_mode(lower, intent)
        self._parse_device_preference(lower, intent)
        self._apply_device_topology_fallback(intent)
        self._parse_extra_requirements(lower, intent)
        self._parse_edit_operations(lower, intent)
        self._parse_explain_focus(lower, intent)
        self._parse_target_scope(lower, intent)
        self._parse_hard_constraints(lower, intent)
        self._calc_confidence(intent)
        intent.source = "rule_based"
        return intent

    def _detect_requested_actions(self, text: str) -> List[str]:
        # Trích tất cả action có mặt trong câu để hỗ trợ input đa ý trong 1 request.
        actions: List[str] = []

        has_modify = (
            self._has_pattern(text, self._REMOVE_PATTERNS)
            or self._has_pattern(text, self._ADD_PATTERNS)
            or self._has_pattern(text, self._MODIFY_PATTERNS)
        )
        if has_modify:
            actions.append("modify")

        if self._has_pattern(text, self._VALIDATE_PATTERNS):
            actions.append("validate")
        if self._has_pattern(text, self._EXPLAIN_PATTERNS):
            actions.append("explain")
        if self._has_pattern(text, self._OPTIMIZE_PATTERNS):
            actions.append("optimize")
        if self._has_pattern(text, self._COMPARE_PATTERNS):
            actions.append("compare")

        # Mặc định vẫn có create nếu không có action nào hoặc có topology/parameter thiết kế.
        has_design_signal = bool(
            self._detect_topology(text) != "unknown - this topology cannot be detected"
            or self._extract_number(text, [
                r"gain\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
                r"dùng\s*(?:nguồn\s*)?([0-9]+(?:\.[0-9]+)?)\s*v",
                r"\b([0-9]+(?:\.[0-9]+)?)\s*v\b",
            ]) is not None
            or self._has_pattern(text, [r"\bthiết\s*kế\b", r"\btạo\s*mạch\b", r"\bdesign\b", r"\bgenerate\b"])
        )
        
        if not actions:
            actions.insert(0, "create")
        elif has_design_signal and "modify" not in actions:
            actions.insert(0, "create")


        # Khử trùng lặp, giữ thứ tự.
        unique_actions: List[str] = []
        for act in actions:
            if act not in unique_actions:
                unique_actions.append(act)
        return unique_actions

    def _detect_topology(self, text: str) -> str:
        # Nhận diện mạch từ key
        priority_order = ["instrumentation", "differential", "non_inverting", "inverting",
                          "class_ab", "class_a", "class_b", "class_c", "class_d",
                          "common_emitter", "common_base", "common_collector",
                          "common_source", "common_drain", "common_gate",
                          "darlington", "multi_stage",]
        
        # ưu tiên nhận diện các loại mạch đặc thù trước (instrumentation, differential, non-inverting, inverting) rồi mới đến các loại mạch chung chung (common emitter/source/collector/gate).
        for topo in priority_order:
            patterns = CIRCUIT_TYPE_KEYWORDS.get(topo, [])
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    return topo

        return "unknown - this topology cannot be detected"

    def _extract_number(self, text: str, patterns: List[str]) -> Optional[float]:
        # Extract giá trị đầu tiên match từ danh sách patterns.
        for pat in patterns:
            mat = re.search(pat, text, re.IGNORECASE)
            if mat:
                try:
                    return float(mat.group(1))
                except (ValueError, IndexError):
                    pass
        return None

    def _has_pattern(self, text: str, patterns: List[str]) -> bool:
        # Kiểm tra nếu bất kỳ pattern nào trong danh sách khớp với text.
        return any(re.search(pat, text, re.IGNORECASE) for pat in patterns)

    def _parse_circuit_type(self, text: str, intent: CircuitIntent) -> None:
        # Nhận diện cấu trúc/topology của mạch từ text → gán topo + loại mạch
        # Prefer multi-stage when user explicitly asks stage count/chain/coupling between stages.
        stage_chain_patterns = [
            r"\b(ce|cb|cc|cs|cd|cg)\s*[-–/ ]\s*(ce|cb|cc|cs|cd|cg)\b",
            r"\b(ce|cb|cc|cs|cd|cg)\b.{0,24}\b(ce|cb|cc|cs|cd|cg)\b",
            r"\bcscd\b|\bcecc\b|\bcecb\b|\bcscg\b",
        ]
        if self._has_pattern(text, CIRCUIT_TYPE_KEYWORDS.get("multi_stage", [])) and self._has_pattern(text, stage_chain_patterns):
            intent.topology = "multi_stage"
            intent.circuit_type = "multi_stage"
            return

        topology = self._detect_topology(text)
        intent.topology = topology
        intent.circuit_type = CIRCUIT_TYPE_MAP.get(topology, topology)
    
    def _parse_gain(self, text: str, intent: CircuitIntent) -> None:
        # Trích gain(độ khuếch đại) mục tiêu từ text.
        range_match = re.search(
            r"(?:gain|av|khuếch\s*đại|hệ\s*số\s*khuếch\s*đại)\s*(?:khoảng|tầm|xấp\s*xỉ|tu\s*|từ)?\s*"
            r"(-?[0-9]+(?:\.[0-9]+)?)\s*(?:-|đến|to|~)\s*(-?[0-9]+(?:\.[0-9]+)?)",
            text,
            re.IGNORECASE,
        )
        if range_match:
            try:
                low = float(range_match.group(1))
                high = float(range_match.group(2))
                intent.gain_target = (low + high) / 2.0
                return
            except ValueError:
                pass

        intent.gain_target = self._extract_number(text, [
            r"gain\s*(?:khoảng|tầm|xấp\s*xỉ)?\s*[=:]?\s*(-?[0-9]+(?:\.[0-9]+)?)",
            r"gain\s*[=:]?\s*(-?[0-9]+(?:\.[0-9]+)?)",
            r"khuếch\s*đại\s*(?:khoảng|tầm|xấp\s*xỉ)?\s*[=:]?\s*(-?[0-9]+(?:\.[0-9]+)?)",
            r"khuếch\s*đại\s*[=:]?\s*(-?[0-9]+(?:\.[0-9]+)?)",
            r"av\s*[=:]?\s*(-?[0-9]+(?:\.[0-9]+)?)",
            r"hệ\s*số\s*khuếch\s*đại\s*[=:]?\s*(-?[0-9]+(?:\.[0-9]+)?)",
            r"(-?[0-9]+(?:\.[0-9]+)?)\s*(?:lần|times|x)\b",
        ])

    def _parse_vcc(self, text: str, intent: CircuitIntent) -> None:
        # Trích giá trị VCC (điện áp nguồn) từ text.
        intent.vcc = self._extract_number(text, [
            r"\bvcc\b\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*v?",  # ưu tiên VCC rõ ràng
            r"\bsupply\b\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*v?",  # supply 12V
            r"dùng\s*(?:nguồn\s*)?([0-9]+(?:\.[0-9]+)?)\s*v",      # dùng nguồn 12V
            r"\bnguồn\b\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*v",    # nguồn 12V
            r"\b([0-9]+(?:\.[0-9]+)?)\s*v\b",                      # số kèm đơn vị V (bắt buộc có 'v')
        ])

    def _parse_frequency(self, text: str, intent: CircuitIntent) -> None:
        # kHz trước để tránh match nhầm Hz
        khz = self._extract_number(text, [
            r"\b(\d+(?:\.\d+)?)\s*k\s*hz\b",
            r"\b(\d+(?:\.\d+)?)\s*khz\b",
            r"\btần\s*số\s*[=:]?\s*(\d+(?:\.\d+)?)\s*k\b",
            r"\bfreq(?:uency)?\s*[=:]?\s*(\d+(?:\.\d+)?)\s*k\b",
        ])
        if khz is not None:
            intent.frequency = khz * 1000
            return
        
        intent.frequency = self._extract_number(text, [
            r"\b(\d+(?:\.\d+)?)\s*hz\b",
            r"\btần\s*số\s*[=:]?\s*(\d+(?:\.\d+)?)\b",
            r"\bfreq(?:uency)?\s*[=:]?\s*(\d+(?:\.\d+)?)\b",
            r"\bf\s*[=:]?\s*(\d+(?:\.\d+)?)\b",
        ])

    def _parse_input_channels(self, text: str, intent: CircuitIntent) -> None:
        # Parse number of channels from text (e.g. "2 kênh", "stereo").
        if self._has_pattern(text, [r"\bstereo\b", r"2\s*kênh", r"2\s*kenh", r"2\s*channels?"]):
            intent.input_channels = 2
            return
        m = re.search(r"(\d+)\s*(?:kênh|kenh|channels?|ch)\b", text, re.IGNORECASE)
        if m:
            intent.input_channels = max(1, int(m.group(1)))

    def _parse_channel_inputs(self, text: str, intent: CircuitIntent) -> None:
        # Parse per-channel input amplitude and optional frequency.
        channel_inputs: Dict[str, Dict[str, Optional[float]]] = {}
        for m in re.finditer(
            r"(?:ch|kênh|kenh)\s*([0-9]+)\s*[:=]?\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(mv|v)"
            r"(?:\s*[,;]?\s*(?:at|@|tần\s*số|tan\s*so|f(?:req(?:uency)?)?)\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(hz|khz))?",
            text,
            re.IGNORECASE,
        ):
            idx = int(m.group(1))
            amp = float(m.group(2))
            amp_unit = (m.group(3) or "v").lower()
            if amp_unit == "mv":
                amp *= 1e-3
            freq_val: Optional[float] = None
            if m.group(4):
                freq_val = float(m.group(4))
                freq_unit = (m.group(5) or "hz").lower()
                if freq_unit == "khz":
                    freq_val *= 1000
            channel_inputs[f"CH{idx}"] = {
                "amplitude_v": amp,
                "frequency_hz": freq_val,
            }

        if channel_inputs:
            intent.channel_inputs = channel_inputs
            intent.input_channels = max(intent.input_channels, len(channel_inputs))

    def _parse_voltage_range(self, text: str, intent: CircuitIntent) -> None:
        # Parse explicit voltage range: "-1V..1V", "0-5V", "range 0 to 3.3V".
        patterns = [
            r"([-+]?[0-9]+(?:\.[0-9]+)?)\s*v\s*(?:to|\-|\.\.|~)\s*([-+]?[0-9]+(?:\.[0-9]+)?)\s*v",
            r"(?:range|dải|phạm\s*vi)\s*([-+]?[0-9]+(?:\.[0-9]+)?)\s*(?:to|\-|\.\.|~)\s*([-+]?[0-9]+(?:\.[0-9]+)?)\s*v",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if not m:
                continue
            v1 = float(m.group(1))
            v2 = float(m.group(2))
            intent.voltage_range = {"min": min(v1, v2), "max": max(v1, v2)}
            return

    def _parse_flags(self, text: str, intent: CircuitIntent) -> None:
        # Phân tích các flag yêu cầu đặc biệt.
        intent.high_cmr = self._has_pattern(text, [
            r"\bcmrr\b", r"high\s*cmrr", r"good\s*cmrr",
            r"common[\s-]*mode\s*rejection",
        ])
        
        intent.output_buffer = self._has_pattern(text, [
            r"\boutput\s*buffer\b", r"\bbuffer\s*output\b", r"\bbuffer\s*stage\b",
            r"\bbuffered\s*output\b", r"\bemitter\s*follower\b", r"\bsource\s*follower\b",
        ])
        
        intent.power_output = self._has_pattern(text, [
            r"\bpower\s*amp(?:lifier)?\b", r"\bpower\s*output\b", r"\bhigh\s*power\b",
            r"công\s*suất", r"ampli\s*công\s*suất",
        ])

    def _parse_input_mode(self, text: str, intent: CircuitIntent) -> None:
        # Nhận diện mạch single-ended hay differential từ text.
        if self._has_pattern(text, [
            r"differential[\s_-]*mode", r"differential[\s_-]*signal",
            r"\bdifferential\b", r"differentially",
            r"differential[\s_-]*ended",
            r"input\s*dạng\s*vi\s*sai", r"tín\s*hiệu\s*vi\s*sai",
        ]): intent.input_mode = "differential"

    def _parse_supply_mode(self, text: str, intent: CircuitIntent) -> None:
        # Nhận diện mạch dùng nguồn đơn hay nguồn đôi từ text.
        if self._has_pattern(text, [
            r"single[\s_-]*supply", r"single[\s_-]*ended[\s_-]*supply",
            r"nguồn\s*đơn", r"nguồn\s*một\s*chiều", r"nguồn\s*một\s*nguồn",
            r"one[\s_-]*supply",
        ]): intent.supply_mode = "single_supply"
        
        elif self._has_pattern(text, [
            r"dual[\s_-]*supply", r"dual[\s_-]*ended[\s_-]*supply",
            r"split[\s_-]*supply", r"bipolar[\s_-]*supply",
            r"nguồn\s*đôi", r"nguồn\s*hai\s*chiều", r"nguồn\s*đối\s*xứng",
            r"hai[\s_-]*nguồn", r"\+/-",
        ]): intent.supply_mode = "dual_supply"

    def _parse_device_preference(self, text: str, intent: CircuitIntent) -> None:
        # Nhận diện loại linh kiện ưu tiên (BJT, MOSFET, OpAmp) từ text.
        if self._has_pattern(text, [
            r"\bbjt\b", r"transistor\s*lưỡng\s*cực",
            r"bipolar[\s_-]*junction[\s_-]*transistor",
            r"bipolar[\s_-]*transistor", r"\bbipolar\b",
            r"transistor\s*bjt", r"bjt\s*stage", r"tầng\s*bjt",
        ]): intent.device_preference = "bjt"
        
        elif self._has_pattern(text, [
            r"\bmosfet\b", r"\bfet\b",
            r"metal[\s_-]*oxide[\s_-]*semiconductor[\s_-]*fet",
            r"mos[\s_-]*fet", r"mosfet\s*stage", r"tầng\s*mosfet",
            r"transistor\s*mosfet",
        ]): intent.device_preference = "mosfet"
        
        elif self._has_pattern(text, [
            r"\bop[\s-]*amp\b", r"\bopamp\b",
            r"operational[\s_-]*amplifier",
            r"op[\s_-]*amp\s*stage", r"tầng\s*opamp",
            r"khuếch\s*đại\s*thuật\s*toán",
        ]): intent.device_preference = "opamp"

    def _apply_device_topology_fallback(self, intent: CircuitIntent) -> None:
        """Infer a default topology when user indicates device family but not explicit topology."""
        unknown_topology = not intent.circuit_type or intent.circuit_type.startswith("unknown")
        if not unknown_topology:
            return

        default_by_device = {
            "opamp": "non_inverting",
            "bjt": "common_emitter",
            "mosfet": "common_source",
        }
        fallback = default_by_device.get(intent.device_preference)
        if fallback:
            intent.topology = fallback
            intent.circuit_type = fallback

    def _parse_extra_requirements(self, text: str, intent: CircuitIntent) -> None:
        # Trích xuất các yêu cầu bổ sung như low_noise, high_bandwidth, rail_to_rail, ac_coupled từ text.
        extras = []
        if self._has_pattern(text, [
            r"low[\s_-]*noise", r"nhiễu\s*thấp", r"ít\s*nhiễu",
            r"noise[\s_-]*performance", r"noise[\s_-]*optimized",
            r"noise[\s_-]*reduction", r"noise[\s_-]*figure",
        ]): extras.append("low_noise")
        
        if self._has_pattern(text, [
            r"high[\s_-]*bandwidth", r"băng\s*thông\s*rộng",
            r"wide[\s_-]*bandwidth", r"băng\s*tần\s*rộng",
            r"bandwidth[\s_-]*optimized", r"tốc\s*độ\s*cao",
        ]): extras.append("high_bandwidth")
        
        if self._has_pattern(text, [
            r"rail[\s_-]*to[\s_-]*rail", r"railtorail", r"rail2rail",
            r"đầu\s*ra\s*rail\s*to\s*rail", r"biên\s*độ\s*toàn\s*dải",
        ]): extras.append("rail_to_rail")
        
        if self._has_pattern(text, [
            r"ac[\s_-]*coupled", r"ac[\s_-]*coupling",
            r"ghép\s*ac", r"ghép\s*tụ",
            r"ac[\s_-]*input", r"ac[\s_-]*output",
        ]): extras.append("ac_coupled")
        
        intent.extra_requirements = extras

    def _parse_intent_type(self, text: str, intent: CircuitIntent) -> None:
        # Nhận diện intent hỗn hợp, sau đó chọn intent chính để route pipeline.
        actions = self._detect_requested_actions(text)
        intent.requested_actions = actions

        # Ưu tiên intent tác vụ cao hơn create khi có xung đột.
        if "modify" in actions:
            intent.intent_type = "modify"
        elif "validate" in actions:
            intent.intent_type = "validate"
        elif "compare" in actions:
            intent.intent_type = "compare"
        elif "optimize" in actions:
            intent.intent_type = "optimize"
        elif "explain" in actions and "create" not in actions:
            intent.intent_type = "explain"
        else:
            intent.intent_type = "create"

    def _parse_explain_focus(self, text: str, intent: CircuitIntent) -> None:
        # Bắt yêu cầu giải thích sâu theo linh kiện ngay cả khi câu chứa cả "thiết kế".
        if "explain" not in intent.requested_actions:
            return

        if self._has_pattern(text, [
            r"\bchi\s*tiết\b", r"\btừng\s*linh\s*kiện\b", r"\bphân\s*tích\s*chi\s*tiết\b", r"\bdetailed\b",
        ]):
            intent.explain_detail_level = "detailed"

        focus: List[str] = []
        for comp in re.findall(r"\b(?:r|c|q|u|d|l)\d+\b", text, re.IGNORECASE):
            normalized = comp.upper()
            if normalized not in focus:
                focus.append(normalized)

        # Hỗ trợ tên linh kiện CE phổ biến khi user viết dạng RC/RE không số.
        for named in re.findall(r"\b(?:r1|r2|rc|re|rb|cin|cout|cc)\b", text, re.IGNORECASE):
            normalized = named.upper()
            if normalized not in focus:
                focus.append(normalized)

        intent.explain_focus_components = focus

    def _parse_edit_operations(self, text: str, intent: CircuitIntent) -> None:
        # Trích xuất các thao tác chỉnh sửa từ text.
        if intent.intent_type != "modify":
            return
        ops: List[EditOperation] = []

        # Pattern: "thêm R1 10k" hoặc "add resistor 10k"
        for m in re.finditer(
            r"(?:thêm|add|bổ\s*sung|insert)\s+"
            r"(?:một\s+|a\s+)?"
            r"(resistor|capacitor|transistor|opamp|tụ|trở|điện\s*trở|tụ\s*điện|bjt|mosfet|cuộn\s*cảm|inductor)"
            r"(?:\s+([A-Za-z][A-Za-z0-9]*))?"  # comp_id: phải bắt đầu bằng chữ
            r"(?:\s+(?:giá\s*trị\s*)?(\d+(?:\.\d+)?)\s*(k|m|u|n|p|Ω|ohm|f|h)?)?",
            text, re.IGNORECASE,
        ):
            comp_type = m.group(1).strip().lower()
            comp_id = m.group(2) or ""
            value = float(m.group(3)) if m.group(3) else None
            unit_prefix = (m.group(4) or "").lower()
            if value and unit_prefix:
                multipliers = {"k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}
                value *= multipliers.get(unit_prefix, 1.0)
            params: Dict[str, Any] = {"type": comp_type}
            if value is not None:
                params["value"] = value
            ops.append(EditOperation(action="add_component", target=comp_id, params=params))

        # Pattern: "xóa R1" hoặc "remove C2"
        for m in re.finditer(
            r"(?:xóa|remove|delete|loại\s*bỏ|bỏ|gỡ)\s+(\w+)",
            text, re.IGNORECASE,
        ):
            target = m.group(1).strip()
            ops.append(EditOperation(action="remove_component", target=target))

        # Pattern: "thay R1 thành 10k" hoặc "change R1 to 10k"
        for m in re.finditer(
            r"(?:thay|đổi|change|replace)\s+(\w+)\s+(?:thành|to|=|bằng)\s+"
            r"(\d+(?:\.\d+)?)\s*(k|m|u|n|p|Ω|ohm)?",
            text, re.IGNORECASE,
        ):
            target = m.group(1).strip()
            new_val = float(m.group(2))
            unit_prefix = (m.group(3) or "").lower()
            multipliers = {"k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12}
            new_val *= multipliers.get(unit_prefix, 1.0)
            ops.append(EditOperation(action="change_value", target=target, params={"new_value": new_val}))

        intent.edit_operations = ops

    def _parse_target_scope(self, text: str, intent: CircuitIntent) -> None:
        # Xác định phạm vi tác động của intent (toàn bộ mạch, tầng vào, tầng ra, mạng phân cực, hồi tiếp) từ text.
        for scope, patterns in self._SCOPE_PATTERNS.items():
            if self._has_pattern(text, patterns):
                intent.target_scope = scope
                return
        intent.target_scope = "entire_circuit"

    def _parse_hard_constraints(self, text: str, intent: CircuitIntent) -> None:
        # Trích xuất hard constraints từ text.
        constraints: Dict[str, Any] = {}
        
        # gain min/max
        m = re.search(r"gain\s*(?:>=?|tối\s*thiểu|min(?:imum)?)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            constraints["gain_min"] = float(m.group(1))
        m = re.search(r"gain\s*(?:<=?|tối\s*đa|max(?:imum)?)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            constraints["gain_max"] = float(m.group(1))
        
        # vcc max
        m = re.search(r"vcc\s*(?:<=?|max|tối\s*đa)\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            constraints["vcc_max"] = float(m.group(1))
        
        # Không lưu trùng intent.vcc/gain_target vào hard_constraints (chỉ lưu constraint thực sự)
        intent.hard_constraints = constraints

    def _calc_confidence(self, intent: CircuitIntent) -> None:
        # Tính điểm tin cậy dựa trên kết quả phân tích regex.
        if intent.circuit_type and not intent.circuit_type.startswith("unknown"):
            intent.confidence = 0.6
        else:
            intent.confidence = 0.1
            return
    
        bonuses = [(intent.gain_target, 0.1),
                   (intent.vcc, 0.1),
                   (intent.frequency, 0.05),
                   (intent.extra_requirements, 0.05)]
        
        for attr, points in bonuses:
            if attr:
                intent.confidence += points
        intent.confidence = min(intent.confidence, 0.90)

            
    #  LLM-enhanced parser
    def _llm_extract(self, user_text: str, mode: Optional["LLMMode"] = None) -> Optional[CircuitIntent]:
        # Trích xuất intent từ LLM router.
        if not self._router:
            return None
        
        # Tạo prompt để hướng dẫn model thực hiện yêu cầu
        system_prompt = self._build_extraction_prompt()
        obj = self._call_llm_extraction(system_prompt, user_text, mode=mode)
        
        if obj is None:
            return None
        
        # Đưa kết quả về intent
        return self._build_intent_from_llm(user_text, obj)
    
    def _build_extraction_prompt(self) -> str:
        # Tạo prompt cho LLM
        system = (
            "You are an electronics circuit intent extraction engine.\n"
            "Given a user request in Vietnamese or English, extract structured intent and output ONLY a valid JSON object.\n"
            "Do NOT include any explanation, markdown, or extra text — just the raw JSON.\n\n"

            "## OUTPUT SCHEMA\n"
            "{\n"
            '  "intent_type":        string,   // REQUIRED. One of: "create"|"modify"|"validate"|"explain"\n'
            '  "circuit_type":       string,   // REQUIRED. One of:\n'
            '                                  //   BJT:   common_emitter | common_base | common_collector | darlington | multi_stage\n'
            '                                  //   FET:   common_source  | common_drain | common_gate\n'
            '                                  //   OpAmp: inverting | non_inverting | differential | instrumentation\n'
            '                                  //   Power: class_a | class_ab | class_b | class_c | class_d\n'
            '                                  //   Other: unknown\n'
            '  "gain_target":        number | null,   // Voltage gain magnitude (e.g. 10 for 20dB)\n'
            '  "vcc":                number | null,   // Supply voltage in Volts (e.g. 12 for "12V")\n'
            '  "frequency":          number | null,   // Operating/cutoff frequency in Hz (e.g. 1000 for "1kHz")\n'
            '  "input_channels":     number,          // Number of input channels, default 1\n'
            '  "channel_inputs":      object,          // Per-channel params. Example: {"CH1": {"amplitude_v": 0.02, "frequency_hz": 1000}}\n'
            '  "voltage_range":       object,          // Signal voltage range. Example: {"min": -1.0, "max": 1.0}\n'
            '  "input_mode":         string,          // "single_ended" | "differential". Default: "single_ended"\n'
            '  "high_cmr":           boolean,         // High CMRR required? Default: false\n'
            '  "output_buffer":      boolean,         // Low-impedance output buffer required? Default: false\n'
            '  "power_output":       boolean,         // Is this a power amplifier stage? Default: false\n'
            '  "supply_mode":        string,          // "auto" | "single_supply" | "dual_supply". Default: "auto"\n'
            '  "device_preference":  string,          // "auto" | "bjt" | "mosfet" | "opamp". Default: "auto"\n'
            '  "extra_requirements": string[],        // Tags from: ["low_noise","high_bandwidth","rail_to_rail","ac_coupled","low_power","high_voltage"]\n'
            '  "edit_operations":    array,           // Only for intent_type="modify". Empty array [] otherwise.\n'
            '                                         // Each item: { "action": string, "target": string, "params": object }\n'
            '                                         // action: "add_component"|"remove_component"|"replace_component"|"change_value"|"change_connection"\n'
            '                                         // target: component name or node (e.g. "R1", "collector", "feedback_network")\n'
            '                                         // params: { "value": ..., "unit": ..., "component_type": ... } as applicable\n'
            '  "target_scope":       string,          // "entire_circuit"|"input_stage"|"output_stage"|"bias_network"|"feedback_loop"\n'
            '  "hard_constraints":   object,          // Must-satisfy limits, e.g. {"gain_min": 10, "vcc_max": 15, "bandwidth_min": 20000}\n'
            '  "soft_preferences":   string[],        // Nice-to-have, e.g. ["low_noise", "small_footprint", "low_cost"]\n'
            '  "confidence":         number           // 0.0-1.0: how certain you are about the extraction\n'
            "}\n\n"

            "## EXTRACTION RULES\n\n"

            "### Numeric Values\n"
            "- Extract ALL numeric values mentioned: gain, voltage, frequency, resistance, etc.\n"
            "- Convert units: '12V'→vcc=12, '1kHz'→frequency=1000, '100kΩ'→params.value=100000\n"
            "- If gain is given in dB, convert to linear: 20dB → gain=10, 40dB → gain=100\n\n"

            "### Vietnamese Vocabulary Mapping\n"
            "- khuếch đại / mạch khuếch đại = amplifier circuit\n"
            "- nguồn / điện áp nguồn = supply voltage (VCC)\n"
            "- tần số = frequency; độ lợi / hệ số khuếch đại = gain\n"
            "- CE / cực phát chung = common_emitter\n"
            "- CB / cực nền chung = common_base\n"
            "- CC / cực thu chung / lặp phát = common_collector\n"
            "- MOSFET nguồn chung = common_source\n"
            "- khuếch đại vi sai = differential amplifier\n"
            "- khuếch đại đảo = inverting; không đảo = non_inverting\n\n"

            "### Edit Operations (intent_type = 'modify')\n"
            "- 'thêm R 10k vào collector'  → action='add_component',    target='collector', params={value:10000, unit:'ohm', component_type:'resistor'}\n"
            "- 'xóa R1' / 'bỏ R1'         → action='remove_component', target='R1',        params={}\n"
            "- 'thay R1 thành 10k'         → action='change_value',     target='R1',        params={value:10000, unit:'ohm'}\n"
            "- 'đổi Q1 sang MOSFET'        → action='replace_component',target='Q1',        params={component_type:'mosfet'}\n"
            "- 'đổi kết nối R2 sang base'  → action='change_connection', target='R2',       params={node:'base'}\n\n"

            "### Defaults & Fallbacks\n"
            "- If a field cannot be determined from the request, use null for numbers and default strings as specified.\n"
            "- Set confidence < 0.5 if the request is vague or ambiguous.\n"
            "- If circuit_type is unclear but device is known (e.g. 'mạch dùng BJT'), set circuit_type='unknown' and device_preference='bjt'.\n"
        )
        return system
    
    def _call_llm_extraction(self, system_prompt: str, user_text: str, mode: Optional["LLMMode"] = None) -> Optional[dict]:
        # Gọi LLM router để trích xuất json
        from app.application.ai.llm_router import LLMRole
        
        obj = self._router.chat_json(
            LLMRole.GENERAL,
            mode=mode,
            system=system_prompt,
            user_content=user_text
        )
        if obj is None:
            return None
        return obj

    def _build_intent_from_llm(self, user_text: str, obj: dict) -> CircuitIntent:
        # Chuyển đổi phản hồi JSON từ LLM thành circuit obj
        intent = CircuitIntent(raw_text=user_text, source="llm")
        
        # phân tích các đặc thù cơ bản
        self._fill_basic_fields(intent, obj)
        self._parse_llm_edit_operations(intent, obj)
        self._parse_explain_fields(intent, obj)
        
        if not intent.requested_actions:
            intent.requested_actions = self._detect_requested_actions(user_text.lower())
        return intent
    
    def _fill_basic_fields(self, intent: CircuitIntent, obj: dict) -> None: 
        # Map các field json -> intent
        intent.intent_type = str(obj.get("intent_type", "create"))
        intent.circuit_type = str(obj.get("circuit_type", "unknown"))
        intent.topology = intent.circuit_type
        
        intent.gain_target = obj.get("gain_target")
        intent.vcc = obj.get("vcc")
        intent.frequency = obj.get("frequency")
        intent.input_channels = int(obj.get("input_channels", 1) or 1)
        channel_inputs = obj.get("channel_inputs", {})
        if isinstance(channel_inputs, dict):
            normalized_channels: Dict[str, Dict[str, Optional[float]]] = {}
            for key, val in channel_inputs.items():
                if isinstance(val, dict):
                    normalized_channels[str(key).upper()] = {
                        "amplitude_v": (float(val["amplitude_v"]) if val.get("amplitude_v") is not None else None),
                        "frequency_hz": (float(val["frequency_hz"]) if val.get("frequency_hz") is not None else None),
                    }
            intent.channel_inputs = normalized_channels
        voltage_range = obj.get("voltage_range", {})
        if isinstance(voltage_range, dict):
            vmin = voltage_range.get("min")
            vmax = voltage_range.get("max")
            intent.voltage_range = {
                "min": float(vmin) if vmin is not None else None,
                "max": float(vmax) if vmax is not None else None,
            }
        
        intent.input_mode = str(obj.get("input_mode", "single_ended"))
        intent.high_cmr = bool(obj.get("high_cmr", False))
        intent.output_buffer = bool(obj.get("output_buffer", False))
        intent.power_output = bool(obj.get("power_output", False))
        
        intent.supply_mode = str(obj.get("supply_mode", "auto"))
        intent.device_preference = str(obj.get("device_preference", "auto"))
        
        intent.extra_requirements = obj.get("extra_requirements", [])
        intent.confidence = float(obj.get("confidence", 0.5))
        
        intent.target_scope = str(obj.get("target_scope", "entire_circuit"))
        intent.hard_constraints = obj.get("hard_constraints", {})
        intent.soft_preferences = obj.get("soft_preferences", [])
        
    def _parse_llm_edit_operations(self, intent: CircuitIntent, obj: dict) -> None:
        # Phân tích nhận diện edit_operations từ json
        raw_ops = obj.get("edit_operations", []) # Json phản hồi
       
        for raw_op in raw_ops:
            if isinstance(raw_op, dict):
                intent.edit_operations.append(EditOperation(
                    action=str(raw_op.get("action", "")),
                    target=str(raw_op.get("target", "")),
                    params=raw_op.get("params", {}),
                ))
        
    def _parse_explain_fields(self, intent: CircuitIntent, obj: dict) -> None:
        # Phân tích các field hỗ trợ cho explain intent
        raw_actions = obj.get("requested_actions", [])
        if isinstance(raw_actions, list):
            intent.requested_actions = [str(a) for a in raw_actions if str(a)] # phần tử -> string
            
        # Chi tiết giải thích: ưu tiên "detailed" nếu có, mặc định "basic"
        raw_detail = str(obj.get("explain_detail_level", "basic")).strip().lower()
        intent.explain_detail_level = "detailed" if raw_detail == "detailed" else "basic"
    
        # Các thành phần cần tập trung giải thích, chuẩn hóa thành uppercase và loại bỏ trùng lặp.
        raw_focus = obj.get("explain_focus_components", [])
        if isinstance(raw_focus, list):
            dedup_focus: List[str] = []

            # Chuẩn hóa tên linh kiện thành uppercase
            for item in raw_focus:
                item_norm = str(item).strip().upper()
                
                # Loại bỏ trùng lặp và giữ nguyên thứ tự
                if item_norm and item_norm not in dedup_focus:
                    dedup_focus.append(item_norm)
            # Gán kết quả đã chuẩn hóa và khử trùng lặp vào intent
            intent.explain_focus_components = dedup_focus


    #  Merge intents (rule-based và LLM intents)
    def _merge_intents(self, rule: CircuitIntent, llm: CircuitIntent) -> CircuitIntent:
        merged = CircuitIntent(raw_text=rule.raw_text)

        # Intent type: ưu tiên LLM nếu không phải default "create"
        if llm.intent_type != "create":
            merged.intent_type = llm.intent_type
        else:
            merged.intent_type = rule.intent_type

        # Ưu tiên LLM cho circuit_type nếu không phải unknown
        if llm.circuit_type and llm.circuit_type != "unknown":
            merged.circuit_type = llm.circuit_type
            merged.topology = llm.topology
        else:
            merged.circuit_type = rule.circuit_type
            merged.topology = rule.topology

        # Số liệu: ưu tiên LLM, fallback rule
        merged.gain_target = llm.gain_target if llm.gain_target is not None else rule.gain_target
        if (
            rule.gain_target is not None
            and llm.gain_target is not None
            and abs(rule.gain_target) >= 5
            and abs(llm.gain_target) < 5
            and re.search(r"(?:gain|av|khuếch\s*đại)", rule.raw_text, re.IGNORECASE)
        ):
            merged.gain_target = rule.gain_target
        merged.vcc = llm.vcc if llm.vcc is not None else rule.vcc
        merged.frequency = llm.frequency if llm.frequency is not None else rule.frequency
        merged.input_channels = llm.input_channels if llm.input_channels > 1 else rule.input_channels
        merged.channel_inputs = llm.channel_inputs if llm.channel_inputs else rule.channel_inputs
        merged.voltage_range = llm.voltage_range if llm.voltage_range else rule.voltage_range


        # Flags: merge
        merged.input_mode = llm.input_mode if llm.input_mode != "single_ended" else rule.input_mode
        merged.high_cmr = llm.high_cmr or rule.high_cmr
        merged.output_buffer = llm.output_buffer or rule.output_buffer
        merged.power_output = llm.power_output or rule.power_output
        merged.supply_mode = llm.supply_mode if llm.supply_mode != "auto" else rule.supply_mode
        merged.device_preference = llm.device_preference if llm.device_preference != "auto" else rule.device_preference

        # Hợp nhất extra_requirements bằng cách lấy union và sắp xếp lại để đảm bảo tính nhất quán.
        extras = set(rule.extra_requirements) | set(llm.extra_requirements)
        merged.extra_requirements = sorted(extras)

        # Edit operations: ưu tiên LLM nếu có, fallback rule
        merged.edit_operations = llm.edit_operations if llm.edit_operations else rule.edit_operations
        merged.target_scope = llm.target_scope if llm.target_scope != "entire_circuit" else rule.target_scope
        merged.requested_actions = list(dict.fromkeys(rule.requested_actions + llm.requested_actions))
        
        merged.explain_detail_level = (
            "detailed"
            if "detailed" in {rule.explain_detail_level, llm.explain_detail_level}
            else "basic"
        )
        
        merged.explain_focus_components = list(dict.fromkeys(
            rule.explain_focus_components + llm.explain_focus_components
        ))

        # Hợp nhất hard/soft constraints từ rule và LLM.
        merged.hard_constraints = {**rule.hard_constraints, **llm.hard_constraints}
        merged.soft_preferences = sorted(set(rule.soft_preferences) | set(llm.soft_preferences))

        # lấy giá trị max để đảm bảo giá trị confidence
        merged.confidence = max(rule.confidence, llm.confidence)

        return merged
