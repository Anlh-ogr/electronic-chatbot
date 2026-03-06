# app/domains/circuits/ai_core/spec_parser.py
""" 1: NLP Spec Parser - Bộ phân tích yêu cầu
Phân tích dữ liệu đầu vào, chuyển ngôn ngữ tự nhiên → đặc tả cấu trúc JSON
Input:  "instrumentation amplifier gain 1000, high CMRR"
Output: UserSpec(circuit_type="instrumentation", gain=1000, high_cmr=True, ...)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

""" lý do sử dụng thư viện
__future__ annotations: tham chiếu đến biến/thamsố/giátrị trước khi tạo xong.
re: xử lý regex để trích xuất thông tin từ văn bản tự nhiên.
logging: ghi log hoạt động của parser để theo dõi và gỡ lỗi.
dataclass, field: tạo lớp dữ liệu đơn giản để lưu trữ spec đã parse.
typing: cung cấp kiểu dữ liệu cho hàm và biến để tăng tính rõ ràng.
"""

logger = logging.getLogger(__name__)



""" Phân tích văn bản tự nhiên từ request (user).
Thông tin: loại mạch, gain, vcc, frequency, các flags và extra requirements.
Tương thích với CircuitIntent trong nlu_service.
"""
@dataclass
class UserSpec:
    circuit_type: str = ""
    gain: Optional[float] = None
    vcc: Optional[float] = None
    frequency: Optional[float] = None       # Tần số hoạt động (Hz)
    high_cmr: bool = False                  # cmrr: common-mode rejection ratio: Loại bỏ nhiễu chung
    input_mode: str = "single_ended"        # mode: single_ended | differential: tín hiệu-gnd | tín hiệu-hai đầu
    output_buffer: bool = False
    power_output: bool = False
    supply_mode: str = "auto"               # auto | dual_supply | single_supply
    device_preference: str = "auto"         # auto | bjt | mosfet | opamp
    extra_requirements: List[str] = field(default_factory=list)
    confidence: float = 0.0                 # 0.0 - 1.0
    source: str = "rule_based"              # rule_based | llm | hybrid
    raw_text: str = ""                      # văn bản gốc

    def to_dict(self) -> dict:
        return {
            "circuit_type": self.circuit_type, "gain": self.gain,
            "vcc": self.vcc, "frequency": self.frequency,
            "high_cmr": self.high_cmr, "input_mode": self.input_mode,
            "output_buffer": self.output_buffer, "power_output": self.power_output,
            "supply_mode": self.supply_mode, "device_preference": self.device_preference,
            "extra_requirements": self.extra_requirements,
            "confidence": round(self.confidence, 3), "source": self.source,
            "raw_text": self.raw_text,
        }


# ── Danh sách nhận diện keywords cho từng loại mạch ──
CIRCUIT_TYPE_KEYWORDS = {
    "instrumentation": [
        # existing...
        r"instrumentation", r"measurement\s*amp", r"3[\s-]*op[\s-]*amp", r"in-amp", r"inamp",
        # proposed
        r"instrument\s*amp", r"instrument\s*amplifier", r"precision\s*amp", r"khuếch\s*đại\s*đo\s*lường", r"amp\s*đo\s*lường", r"amp\s*cảm\s*biến", r"sensor\s*amplifier"
    ],
    
    "differential": [
        # existing...
        r"differential", r"difference\s*amp", r"subtractor",
        # proposed
        r"diff\s*amp", r"amp\s*vi\s*sai", r"khuếch\s*đại\s*vi\s*sai", r"mạch\s*vi\s*sai", r"mạch\s*so\s*hiệu",
    ],
    
    "non_inverting": [
        # existing...
        r"non[\s_-]*inverting", r"non_inverting", r"không\s*đảo",
        # proposed
        r"noninv", r"opamp\s*không\s*đảo", r"mạch\s*không\s*đảo", r"gain\s*dương",
    ],
    
    "inverting": [
        # existing...
        r"inverting(?!\s*non)", r"đảo\s*pha",
        # proposed
        r"inv\s*amp", r"opamp\s*đảo", r"mạch\s*đảo", r"khuếch\s*đại\s*đảo", r"gain\s*âm",
    ],
    
    "common_emitter": [
        # existing...
        r"common[\s_-]*emitter", r"\bce\b", r"emitter\s*chung", r"common_emitter",
        # proposed
        r"bjt\s*ce", r"tầng\s*ce", r"mạch\s*ce", r"khuếch\s*đại\s*ce",
    ],
    
    "common_base": [
        # existing...
        r"common[\s_-]*base", r"\bcb\b", r"base\s*chung", r"common_base",
        # proposed
        r"bjt\s*cb", r"tầng\s*cb", r"khuếch\s*đại\s*cb",
    ],
    
    "common_collector": [
        # existing...
        r"common[\s_-]*collector", r"\bcc\b", r"emitter\s*follower", r"collector\s*chung", r"common_collector",
        # proposed
        r"buffer\s*bjt", r"bjt\s*follower", r"voltage\s*follower\s*bjt", r"tầng\s*đệm",
    ],
    
    "common_source": [
        # existing...
        r"common[\s_-]*source", r"\bcs\b", r"source\s*chung", r"common_source",
        # proposed
        r"mosfet\s*cs", r"tầng\s*cs", r"khuếch\s*đại\s*cs",
    ],
    
    "common_drain": [
        # existing...
        r"common[\s_-]*drain", r"\bcd\b", r"source\s*follower", r"drain\s*chung", r"common_drain",
        # proposed
        r"mosfet\s*follower", r"voltage\s*follower\s*mosfet", r"tầng\s*cd", r"mạch\s*đệm\s*mosfet",
    ],
    
    "common_gate": [
        # existing...
        r"common[\s_-]*gate", r"\bcg\b", r"gate\s*chung", r"common_gate",
        # proposed
        r"mosfet\s*cg", r"tầng\s*cg", r"khuếch\s*đại\s*cg",
    ],
    
    "class_a": [
        # existing...
        r"class[\s_-]*a(?![b-z])", r"lớp\s*a\b",
        # proposed
        r"class\s*a\s*amp", r"khuếch\s*đại\s*lớp\s*a", r"amp\s*lớp\s*a",
    ],
    
    "class_ab": [
        # existing...
        r"class[\s_-]*ab", r"lớp\s*ab",
        # proposed
        r"class\s*a\s*b", r"khuếch\s*đại\s*lớp\s*ab",
    ],
    
    "class_b": [
        # existing...
        r"class[\s_-]*b(?![a-z])", r"lớp\s*b\b",
        # proposed
        r"khuếch\s*đại\s*lớp\s*b",
    ],
    
    "class_c": [
        # existing...
        r"class[\s_-]*c(?![a-z])", r"lớp\s*c\b", r"tuned\s*amp",
        # proposed
        r"rf\s*amp", r"khuếch\s*đại\s*rf", r"radio\s*frequency\s*amp",
    ],
    
    "class_d": [
        # existing...
        r"class[\s_-]*d(?![a-z])", r"lớp\s*d\b", r"switching\s*amp",
        # proposed
        r"pwm\s*amp", r"digital\s*amp", r"khuếch\s*đại\s*xung",
    ],
    
    "darlington": [
        # existing...
        r"darlington",
        # proposed
        r"cặp\s*darlington", r"darlington\s*pair", r"transistor\s*kép",
    ],
    
    "multi_stage": [
        # existing...
        r"multi[\s_-]*stage", r"two[\s-]*stage", r"nhiều\s*tầng", r"2\s*tầng", r"cascade", r"multi_stage",
        # proposed
        r"3\s*tầng", r"three[\s-]*stage", r"khuếch\s*đại\s*nhiều\s*tầng", r"amp\s*cascade",
    ],
}


class NLPSpecParser:
    """ Phân tích nntn yêu cầu NLP → UserSpecification nhận diện ý định.
    Fl1: Regex-based extraction (luôn chạy, nhanh).
    Fl2: LLM fallback nếu regex không nhận diện được (circuit_type=unknown)
         là llm_client được inject vào.
    """

    def __init__(self, llm_client: Any = None) -> None:
        """ Khởi tạo parser: phân tích dữ liệu đầu vào.
        llm client: method chat json (mess, system instruction,...)
        tương thích GeminiClient hoặc OpenAICompatibleLLMClient.
        """
        
        self._llm_client = llm_client

    def parse(self, user_text: str) -> UserSpec:
        """ regex trước -> "unknown" -> llm fallback """
        spec = UserSpec(raw_text=user_text)
        text = user_text.lower().strip()

        # Fl1: Regex-based
        self._parse_circuit_type(text, spec)
        self._parse_gain(text, spec)
        self._parse_vcc(text, spec)
        self._parse_frequency(text, spec)
        self._parse_flags(text, spec)
        self._parse_input_mode(text, spec)
        self._parse_supply_mode(text, spec)
        self._parse_device_preference(text, spec)
        self._parse_extra_requirements(text, spec)
        self._calc_confidence(spec)
        spec.source = "rule_based"

        # Fl2: LLM fallback
        if spec.circuit_type == "unknown" and self._llm_client:
            llm_spec = self._llm_parse(user_text)
            if llm_spec and llm_spec.circuit_type != "unknown":
                spec = llm_spec
                spec.source = "llm"

        logger.info(f"Obj chứa thông tin trích xuất: type={spec.circuit_type}, gain={spec.gain}, src={spec.source}")
        return spec



    # llm fallback
    def _llm_parse(self, user_text: str) -> Optional[UserSpec]:
        """ Gọi LLM để phân tích dữ liệu input. """
        try:
            from app.application.ai.gemini_client import GeminiMessage  # type: ignore
            MessageCls = GeminiMessage
        except ImportError:
            try:
                from app.application.ai.llm_client import ChatMessage  # type: ignore
                MessageCls = ChatMessage  # type: ignore
            except ImportError:
                logger.warning("NLPSpecParser: Không tìm thấy message class cho LLM")
                return None

        system = (
            "You are an electronics circuit intent extraction engine.\n"
            "Given a user request (Vietnamese or English), extract structured intent.\n"
            "Output ONLY a JSON object with schema:\n"
            "{\n"
            '  "circuit_type": string,  // common_emitter|common_base|common_collector|'
            'common_source|common_drain|common_gate|inverting|non_inverting|'
            'differential|instrumentation|class_a|class_ab|class_b|class_c|class_d|darlington|multi_stage|unknown\n'
            '  "gain": number|null,\n'
            '  "vcc": number|null,\n'
            '  "frequency": number|null,\n'
            '  "input_mode": "single_ended"|"differential",\n'
            '  "supply_mode": "auto"|"single_supply"|"dual_supply",\n'
            '  "device_preference": "auto"|"bjt"|"mosfet"|"opamp",\n'
            '  "extra_requirements": string[],\n'
            '  "confidence": number\n'
            "}\n"
            "- Understand Vietnamese: CE=common emitter, khuếch đại=amplifier, nguồn=supply\n"
        )
        try:
            obj: Dict[str, Any] = self._llm_client.chat_json(
                messages=[MessageCls(role="user", content=user_text)],
                system_instruction=system,                         # llm hiểu
                create=0.0,                                        # mức độ sáng tạo
                max_tokens=500,
            )
        except Exception as e:
            logger.warning(f"NLPSpecParser LLM fallback error: {e}")
            return None

        spec = UserSpec(raw_text=user_text)
        spec.circuit_type = str(obj.get("circuit_type", "unknown"))
        spec.gain = obj.get("gain")
        spec.vcc = obj.get("vcc")
        spec.frequency = obj.get("frequency")
        spec.input_mode = str(obj.get("input_mode", "single_ended"))
        spec.supply_mode = str(obj.get("supply_mode", "auto"))
        spec.device_preference = str(obj.get("device_preference", "auto"))
        spec.extra_requirements = obj.get("extra_requirements", [])
        spec.confidence = float(obj.get("confidence", 0.5))
        return spec

    def _parse_circuit_type(self, text: str, spec: UserSpec) -> None:
        spec.circuit_type = self._detect_circuit_type(text)

    def _parse_gain(self, text: str, spec: UserSpec) -> None:
        spec.gain = self._extract_gain(text)
    
    def _parse_vcc(self, text: str, spec: UserSpec) -> None:
        """ Trích giá trị VCC (điện áp nguồn) từ text. """
        spec.vcc = self._extract_number(text, [
            # lọc vcc trước - tránh match giá trị khác
            r"\bvcc\b\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*v?",
            
            # nguồn (vns)
            r"\bnguồn\b\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*v?",
            
            # nguồn (eng)
            r"\bsupply\b\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)\s*v?",
            
            # phong cach vns
            r"dùng\s*(?:nguồn\s*)?([0-9]+(?:\.[0-9]+)?)\s*v",
            
            # fallback voltage
            r"\b([0-9]+(?:\.[0-9]+)?)\s*v\b",
        ])

    def _parse_frequency(self, text: str, spec: UserSpec) -> None:
        """ Trích giá trị tần số từ text. """
        # kHz trước để tránh match nhầm Hz
        khz = self._extract_number(text, [
            r"\b(\d+(?:\.\d+)?)\s*k\s*hz\b",
            r"\b(\d+(?:\.\d+)?)\s*khz\b",
            r"\btần\s*số\s*[=:]?\s*(\d+(?:\.\d+)?)\s*k\b",
            r"\bfreq(?:uency)?\s*[=:]?\s*(\d+(?:\.\d+)?)\s*k\b",
        ])
        
        if khz is not None:
            spec.frequency = khz * 1000
            return
        
        # Hz
        spec.frequency = self._extract_number(text, [
            r"\b(\d+(?:\.\d+)?)\s*hz\b",
            r"\btần\s*số\s*[=:]?\s*(\d+(?:\.\d+)?)\b",
            r"\bfreq(?:uency)?\s*[=:]?\s*(\d+(?:\.\d+)?)\b",
            r"\bf\s*[=:]?\s*(\d+(?:\.\d+)?)\b",
        ])

    def _parse_flags(self, text: str, spec: UserSpec) -> None:
        """ Phân tích syntax các flag yêu cầu đặc biệt. """
        spec.high_cmr = self._has_pattern(text, [
            r"\bcmrr\b", r"high\s*cmrr", r"good\s*cmrr", r"common[\s-]*mode\s*rejection",
        ])
        
        spec.output_buffer = self._has_pattern(text, [
            r"\boutput\s*buffer\b", r"\bbuffer\s*output\b", r"\bbuffer\s*stage\b", r"\bbuffered\s*output\b", r"\bemitter\s*follower\b", r"\bsource\s*follower\b",
        ])
        
        spec.power_output = self._has_pattern(text, [
            r"\bpower\s*amp(lifier)?\b", r"\bpower\s*output\b", r"\bhigh\s*power\b", r"công\s*suất", r"ampli\s*công\s*suất",
        ])
            
    def _parse_input_mode(self, text: str, spec: UserSpec) -> None:
        # ưu tiên differential nếu có cả 2 pattern (vì specific hơn)
        if self._has_pattern(text, [r"differential[\s_-]*mode", r"differential[\s_-]*signal", r"differential", r"differentially", r"differential[\s_-]*ended", r"input\sdạng\svi\s*sai", r"tín\shiệu\svi\s*sai"]):
            spec.input_mode = "differential"

    def _parse_supply_mode(self, text: str, spec: UserSpec) -> None:
        # Nhận diện single supply
        if self._has_pattern(text, [r"single[\s_-]*supply", r"single[\s_-]*ended[\s_-]*supply", r"nguồn\s*đơn", r"nguồn\s*một\s*chiều", r"nguồn\s*một\s*nguồn", r"one[\s_-]*supply",]):
            spec.supply_mode = "single_supply"
        # Nhận diện dual supply
        elif self._has_pattern(text, [r"dual[\s_-]*supply", r"dual[\s_-]*ended[\s_-]*supply", r"split[\s_-]*supply", r"bipolar[\s_-]*supply", r"nguồn\s*đôi", r"nguồn\s*hai\s*chiều", r"nguồn\s*đối\s*xứng", r"hai[\s_-]*nguồn", r"\+/-",]):
            spec.supply_mode = "dual_supply"

    def _parse_device_preference(self, text: str, spec: UserSpec) -> None:
        # BJT
        if self._has_pattern(text, [r"\bbjt\b", r"transistor\s*lưỡng\s*cực", r"bipolar[\s_-]*junction[\s_-]*transistor", r"bipolar[\s_-]*transistor", r"bipolar", r"transistor\s*bjt", r"bjt\s*stage", r"tầng\s*bjt",]):
            spec.device_preference = "bjt"
        
        # MOSFET
        elif self._has_pattern(text, [r"\bmosfet\b", r"\bfet\b", r"metal[\s_-]*oxide[\s_-]*semiconductor[\s_-]*fet", r"mos[\s_-]*fet", r"mosfet\s*stage", r"tầng\s*mosfet", r"transistor\s*mosfet",]):
            spec.device_preference = "mosfet"
        
        # OPAMP
        elif self._has_pattern(text, [r"\bop[\s-]*amp\b", r"\bopamp\b", r"operational[\s_-]*amplifier", r"op[\s_-]*amp", r"opamp\s*stage", r"tầng\s*opamp", r"khuếch\s*đại\s*thu\s*động",]):
            spec.device_preference = "opamp"

    def _parse_extra_requirements(self, text: str, spec: UserSpec) -> None:
        extras = []
        # Low noise
        if self._has_pattern(text, [r"low[\s_-]*noise", r"nhiễu\s*thấp", r"ít\s*nhiễu", r"noise[\s_-]*performance", r"noise[\s_-]*optimized", r"noise[\s_-]*reduction", r"noise[\s_-]*minimized", r"noise[\s_-]*figure",]):
            extras.append("low_noise")
        
        # High bandwidth
        if self._has_pattern(text, [r"high[\s_-]*bandwidth", r"băng\s*thông\s*rộng", r"wide[\s_-]*bandwidth", r"băng\s*tần\s*rộng", r"bandwidth[\s_-]*optimized", r"bandwidth[\s_-]*performance", r"tốc\s*độ\s*cao",]):
            extras.append("high_bandwidth")
        
        # Rail-to-rail
        if self._has_pattern(text, [r"rail[\s_-]*to[\s_-]*rail", r"railtorail", r"rail2rail", r"đầu\s*ra\s*rail\s*to\s*rail", r"đầu\s*vào\s*rail\s*to\s*rail", r"biên\s*độ\s*toàn\s*dải",]):
            extras.append("rail_to_rail")
        
        # AC coupled
        if self._has_pattern(text, [r"ac[\s_-]*coupled", r"ac[\s_-]*coupling", r"ghép\s*ac", r"ghép\s*tụ", r"ac[\s_-]*input", r"ac[\s_-]*output",]):
            extras.append("ac_coupled")
        
        spec.extra_requirements = extras


    def _calc_confidence(self, spec: UserSpec) -> None:
        """ Tính điểm tin cậy dựa trên kết quả phân tích regex. """
        if spec.circuit_type and spec.circuit_type != "unknown":
            spec.confidence = 0.6
            if spec.gain is not None:       spec.confidence += 0.1
            if spec.vcc is not None:        spec.confidence += 0.1
            if spec.frequency is not None:  spec.confidence += 0.05
            if spec.extra_requirements:     spec.confidence += 0.05
        else:
            spec.confidence = 0.1


    # Lõi regex
    def _detect_circuit_type(self, text: str) -> str:
        """Detect circuit type từ text bằng regex matching."""
        # Ưu tiên match dài hơn trước (instrumentation trước inverting)
        priority_order = [
            "instrumentation", "differential", "non_inverting", "inverting",
            "class_ab", "class_a", "class_b", "class_c", "class_d",
            "common_emitter", "common_base", "common_collector",
            "common_source", "common_drain", "common_gate",
            "darlington", "multi_stage",
        ]
        for ctype in priority_order:
            patterns = CIRCUIT_TYPE_KEYWORDS.get(ctype, [])
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    return ctype
        return "unknown"

    def _extract_gain(self, text: str) -> Optional[float]:
        """ Trích giá trị gain từ text. """
        return self._extract_number(text, [
            r"gain\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
            r"khuếch\s*đại\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
            r"av\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
            r"hệ\s*số\s*khuếch\s*đại\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
            r"([0-9]+(?:\.[0-9]+)?)\s*(?:lần|times|x)\b",
        ])

    def _extract_number(self, text: str, patterns: List[str]) -> Optional[float]:
        """ Extract số đầu tiên match từ danh sách patterns. """
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except (ValueError, IndexError):
                    pass
        return None

    def _has_pattern(self, text: str, patterns: List[str]) -> bool:
        """Check xem text có match bất kỳ pattern nào không."""
        return any(re.search(pat, text, re.IGNORECASE) for pat in patterns)
