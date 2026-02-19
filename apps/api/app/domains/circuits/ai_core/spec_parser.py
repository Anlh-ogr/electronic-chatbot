# app/domains/circuits/ai_core/spec_parser.py
""" 1: NLP Spec Parser - chuyển ngôn ngữ tự nhiên → spec cấu trúc JSON
Parse yêu cầu tự nhiên của user thành JSON specification có cấu trúc.
Input:  "instrumentation amplifier gain 1000, high CMRR"
Output: UserSpec(circuit_type="instrumentation", gain=1000, high_cmr=True, ...)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

""" lý do sử dụng thư viện
__future__ annotations: tham chiếu đến biến/thamsố/giátrị trước khi tạo xong.
re: xử lý regex để trích xuất thông tin từ văn bản tự nhiên.
logging: ghi log hoạt động của parser để theo dõi và gỡ lỗi.
dataclass, field: tạo lớp dữ liệu đơn giản để lưu trữ spec đã parse.
typing: cung cấp kiểu dữ liệu cho hàm và biến để tăng tính rõ ràng.
"""

logger = logging.getLogger(__name__)


""" Tách thông tin từ yêu cầu.
loại mạch, hệ số khuếch đại, các flags (high CMRR, output buffer, power output), mode (input/supply), device preference, extra requirements.
"""
@dataclass
class UserSpec:
    circuit_type: str = ""
    gain: Optional[float] = None
    high_cmr: bool = False              # cmrr : khả năng loại bỏ tín hiệu chung (common-mode rejection ratio)
    input_mode: str = "single_ended"    # single_ended | differential
    output_buffer: bool = False         # độ lợi
    power_output: bool = False
    supply_mode: str = "auto"           # auto | dual_supply | single_supply
    device_preference: str = "auto"     # auto | bjt | mosfet | opamp
    extra_requirements: List[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "circuit_type": self.circuit_type, "gain": self.gain, "high_cmr": self.high_cmr,
            "input_mode": self.input_mode, "output_buffer": self.output_buffer,
            "power_output": self.power_output, "supply_mode": self.supply_mode,
            "device_preference": self.device_preference, "extra_requirements": self.extra_requirements,
            "raw_text": self.raw_text,
        }


# ── Danh sách nhận diện keywords cho từng loại mạch ──
CIRCUIT_TYPE_KEYWORDS = {
    "instrumentation": [
        r"instrumentation", r"measurement\s*amp", r"3[\s-]*op[\s-]*amp",
        r"in-amp", r"inamp",
    ],
    "differential": [
        r"differential", r"difference\s*amp", r"subtractor",
    ],
    "non_inverting": [
        r"non[\s_-]*inverting", r"non_inverting", r"không\s*đảo",
    ],
    "inverting": [
        r"inverting(?!\s*non)", r"đảo\s*pha",
    ],
    "common_emitter": [
        r"common[\s_-]*emitter", r"\bce\b", r"emitter\s*chung",
        r"common_emitter",
    ],
    "common_base": [
        r"common[\s_-]*base", r"\bcb\b", r"base\s*chung",
        r"common_base",
    ],
    "common_collector": [
        r"common[\s_-]*collector", r"\bcc\b", r"emitter\s*follower",
        r"collector\s*chung", r"common_collector",
    ],
    "common_source": [
        r"common[\s_-]*source", r"\bcs\b", r"source\s*chung",
        r"common_source",
    ],
    "common_drain": [
        r"common[\s_-]*drain", r"\bcd\b", r"source\s*follower",
        r"drain\s*chung", r"common_drain",
    ],
    "common_gate": [
        r"common[\s_-]*gate", r"\bcg\b", r"gate\s*chung",
        r"common_gate",
    ],
    "class_a": [
        r"class[\s_-]*a(?![b-z])", r"lớp\s*a\b",
    ],
    "class_ab": [
        r"class[\s_-]*ab", r"lớp\s*ab",
    ],
    "class_b": [
        r"class[\s_-]*b(?![a-z])", r"lớp\s*b\b",
    ],
    "class_c": [
        r"class[\s_-]*c(?![a-z])", r"lớp\s*c\b", r"tuned\s*amp",
    ],
    "class_d": [
        r"class[\s_-]*d(?![a-z])", r"lớp\s*d\b", r"switching\s*amp",
    ],
    "darlington": [
        r"darlington",
    ],
    "multi_stage": [
        r"multi[\s_-]*stage", r"two[\s-]*stage", r"nhiều\s*tầng", r"2\s*tầng",
        r"cascade", r"multi_stage",
    ],
}


class NLPSpecParser:
    """ Parser yêu cầu NLP → UserSpecification (tách thông tin).
    Hiện tại dùng regex-based extraction.
    Có thể mở rộng thành LLM-based parser trong tương lai.
    """
    def parse(self, user_text: str) -> UserSpec:
        """Parse văn bản tự nhiên thành UserSpec."""
        spec = UserSpec(raw_text=user_text)
        text = user_text.lower().strip()

        # 1. nhận diện loại mạch
        spec.circuit_type = self._detect_circuit_type(text)

        # 2. trích hệ số khuếch đại (gain) nếu có
        spec.gain = self._extract_gain(text)

        # 3. nhận diện các flags khác
        spec.high_cmr = self._has_pattern(text, [
            r"high\s*cmrr?", r"cmrr", r"common[\s-]*mode\s*rejection",
        ])

        spec.output_buffer = self._has_pattern(text, [
            r"output\s*buffer", r"buffer\s*output", r"emitter\s*follower\s*output",
            r"source\s*follower\s*output",
        ])

        spec.power_output = self._has_pattern(text, [
            r"power\s*amp", r"power\s*output", r"công\s*suất",
        ])

        # 4. Input mode
        if self._has_pattern(text, [r"differential\s*input", r"vi\s*sai"]):
            spec.input_mode = "differential"

        # 5. Supply mode
        if self._has_pattern(text, [r"single[\s-]*supply", r"nguồn\s*đơn"]):
            spec.supply_mode = "single_supply"
        elif self._has_pattern(text, [r"dual[\s-]*supply", r"nguồn\s*đôi", r"\+/-"]):
            spec.supply_mode = "dual_supply"

        # 6. Tham khảo devices
        if self._has_pattern(text, [r"\bbjt\b", r"transistor\s*lưỡng\s*cực"]):
            spec.device_preference = "bjt"
        elif self._has_pattern(text, [r"\bmosfet\b", r"\bfet\b"]):
            spec.device_preference = "mosfet"
        elif self._has_pattern(text, [r"\bop[\s-]*amp\b", r"\bopamp\b"]):
            spec.device_preference = "opamp"

        # 7. Extra requirements (low noise, high bandwidth, rail-to-rail, ac-coupled...)
        extras = []
        if self._has_pattern(text, [r"low[\s-]*noise", r"nhiễu\s*thấp"]):
            extras.append("low_noise")
        if self._has_pattern(text, [r"high[\s-]*bandwidth", r"băng\s*thông\s*rộng"]):
            extras.append("high_bandwidth")
        if self._has_pattern(text, [r"rail[\s-]*to[\s-]*rail"]):
            extras.append("rail_to_rail")
        if self._has_pattern(text, [r"ac[\s-]*coupled"]):
            extras.append("ac_coupled")
        spec.extra_requirements = extras

        logger.info(f"Parsed spec: type={spec.circuit_type}, gain={spec.gain}")
        return spec


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
        """Trích giá trị gain từ text."""
        patterns = [
            r"gain\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
            r"khuếch\s*đại\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
            r"av\s*[=:]?\s*([0-9]+(?:\.[0-9]+)?)",
            r"([0-9]+(?:\.[0-9]+)?)\s*(?:lần|times|x)\s*(?:gain|khuếch đại)?",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    pass
        return None

    def _has_pattern(self, text: str, patterns: list) -> bool:
        """Check xem text có match bất kỳ pattern nào không."""
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return True
        return False
