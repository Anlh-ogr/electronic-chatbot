# .\thesis\electronic-chatbot\apps\api\app\application\ai\nlg_service.py
"""Natural Language Generation (NLG) Service.

Sinh câu trả lời tự nhiên (Tiếng Việt) cho user dựa trên kết quả pipeline.

Module này chịu trách nhiệm:
 1. Sinh response thành công: công thức, thông số, cảnh báo
 2. Sinh response lỗi: explain tại sao fail, đề xuất sửa
 3. Sinh clarification: hỏi user khi không chắc
 4. Post-process: chuẩn hóa LaTeX, bảo đảm phương trình đủ

Mode Air/Pro được truyền từ chatbot service để đồng bộ.

Nguyên tắc:
 - Adapter pattern: tầng application, phụ thuộc LLM Router + template fallback
 - LLM priority: LLM đầu tiên, fallback template nếu lỗi
 - Deterministic post-process: bảo đảm output sạch
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING
logger = logging.getLogger(__name__)


from app.application.ai.llm_router import LLMMode

class NLGService:
    """ Natural Language Generation service.
    Sinh câu trả lời tự nhiên (Vietnamese) cho chatbot.
    Dùng LLM role chung theo mode Air/Pro, fallback về template nếu cần.
    """

    def __init__(self) -> None:
        self._router = None
        self._init_router()

    def _init_router(self) -> None:
        # Khởi tạo LLM router
        try:
            from app.application.ai.llm_router import get_router, LLMRole
            router = get_router()
            if router.is_available(LLMRole.GENERAL):
                self._router = router
                logger.info("NLG: LLM Router đã sẵn sàng")
            else:
                logger.info("NLG: Không có LLM API keys, sử dụng template cơ bản")
        except Exception as e:
            logger.warning(f"NLG: Lỗi khởi tạo LLM Router: {e}")


    #  Public API
    def generate_success_response(self, circuit_type: str, gain_actual: Optional[float], gain_target: Optional[float], params: Dict[str, float], gain_formula: str = "", warnings: List[str] = None, template_id: str = "", simulation: Optional[Dict[str, Any]] = None, stage_table: Optional[List[Dict[str, Any]]] = None, mode: Optional["LLMMode"] = None,) -> str:
        # Sinh response khi pipeline thành công
        warnings = warnings or []

        # Sinh phản hồi qua LLM trước
        if self._router:
            try:
                response = self._llm_success_response(
                    circuit_type, gain_actual, gain_target, params,
                    gain_formula, warnings, template_id, mode,
                )
                return self._postprocess_success_response(
                    response,
                    circuit_type,
                    gain_actual=gain_actual,
                    gain_target=gain_target,
                    gain_formula=gain_formula,
                    warnings=warnings,
                    params=params,
                    simulation=simulation or {},
                    stage_table=stage_table or [],
                )
                
            except Exception as e:
                logger.warning(f"NLG: LLM failed: {e}")

        # Fallback: template-based
        response = self._template_success_response(
            circuit_type, gain_actual, gain_target, params,
            gain_formula, warnings, template_id, simulation or {}, stage_table or [],
        )
        return self._postprocess_success_response(
            response,
            circuit_type,
            gain_actual=gain_actual,
            gain_target=gain_target,
            gain_formula=gain_formula,
            warnings=warnings,
            params=params,
            simulation=simulation or {},
            stage_table=stage_table or [],
        )

    def generate_error_response(self, error_msg: str, stage: str, circuit_type: str = "", gain_target: Optional[float] = None, vcc: Optional[float] = None, mode: Optional["LLMMode"] = None,) -> str:
        # Sinh response khi pipeline lỗi + đề xuất
        if self._router:
            try:
                return self._llm_error_response(error_msg, stage, circuit_type, gain_target, vcc, mode,)
            except Exception as e:
                logger.warning(f"NLG LLM lỗi trả về: {e}")

        return self._template_error_response(error_msg, stage, circuit_type, gain_target, vcc,)

    def generate_clarification(self, circuit_type: str = "", missing_fields: List[str] = None, mode: Optional["LLMMode"] = None) -> str:
        # Sinh câu hỏi clarification cho user.
        missing = missing_fields or []

        # Thử LLM trước
        if self._router:
            try:
                return self._llm_clarification(circuit_type, missing, mode)
            except Exception as e:
                logger.warning(f"NLG: LLM clarification failed: {e}")
        
        # Fallback: template-based
        parts = []
        if circuit_type:
            parts.append(f"Tôi nhận diện bạn muốn mạch **{self._format_type(circuit_type)}**.")
        else:
            parts.append("Tôi chưa xác định được loại mạch bạn muốn.")

        if missing:
            parts.append("Vui lòng cung cấp thêm:")
            field_names = {
                "gain": "- **Gain** (hệ số khuếch đại): ví dụ gain 50",
                "vcc": "- **VCC** (điện áp nguồn): ví dụ 12V",
                "frequency": "- **Tần số** hoạt động: ví dụ 1kHz",
                "topology": "- **Topology** (cấu hình mạch): CE, CB, CC, opamp inverting...",
            }
            for f in missing:
                parts.append(field_names.get(f, f"- {f}"))

        return "\n".join(parts)


    #  Template-based responses (fallback)
    def _template_success_response(self, circuit_type: str, gain_actual: Optional[float], gain_target: Optional[float], params: Dict[str, float], gain_formula: str, warnings: List[str], template_id: str, simulation: Dict[str, Any], stage_table: List[Dict[str, Any]],) -> str:
        # Response template khi thành công.
        lines = []
        eq_info = self._build_equation_context(circuit_type)
        lines.append(f"**Đã thiết kế mạch {self._format_type(circuit_type)}** (template: {template_id})")
        lines.append("")

        lines.append("## 1. Hệ phương trình hệ số khuếch đại")
        if gain_formula:
            lines.append(f"- Phương trình Av dùng để thiết kế: **{gain_formula}**")
        else:
            lines.append(f"- Phương trình Av tham chiếu theo cấu hình: **{eq_info['equations']['Av']}**")
        lines.append(f"- Ai: **{eq_info['equations']['Ai']}**")
        lines.append(f"- Zi: **{eq_info['equations']['Zi']}**")
        lines.append(f"- Zo: **{eq_info['equations']['Zo']}**")
        lines.append(f"- Dự đoán waveform đầu ra: {self._build_waveform_inference(circuit_type, gain_actual, gain_target, warnings)}")
        lines.append(self._build_waveform_equation_match_line(simulation))
        lines.extend(self._build_waveform_simulation_block(gain_actual, gain_target, params, warnings))
        lines.append("")

        lines.append("## 2. Chức năng mạch")
        lines.append(f"Mạch {self._format_type(circuit_type)} thực hiện khuếch đại tín hiệu theo cấu hình đã chọn.")
        lines.append("")

        lines.append("## 3. Giải pháp")
        lines.append(f"- Họ linh kiện chủ động: **{eq_info['family']}**")
        lines.append("- Phương trình khuếch đại tham chiếu:")
        lines.append(f"  - **Av:** {eq_info['equations']['Av']}")
        lines.append(f"  - **Ai:** {eq_info['equations']['Ai']}")
        lines.append(f"  - **Zi:** {eq_info['equations']['Zi']}")
        lines.append(f"  - **Zo:** {eq_info['equations']['Zo']}")
        for key, val in eq_info["equations"].items():
            if key in {"Av", "Ai", "Zi", "Zo"}:
                continue
            lines.append(f"  - **{key}:** {val}")
        lines.append("- Thông số quan trọng cần có: " + ", ".join(eq_info["key_params"]))
        lines.append("- Quy trình tìm phương trình:")
        for step in eq_info["workflow"]:
            lines.append(f"  - {step}")
        lines.append("")

        lines.append("## 4. Bước tính toán thiết kế")

        if gain_formula:
            lines.append(f"**Công thức gain (KaTeX):** $$ {self._to_katex_formula(gain_formula)} $$")
        else:
            lines.append(f"**Công thức gain tham chiếu (KaTeX):** $$ {self._to_katex_formula(eq_info['equations']['Av'])} $$")

        stage_formula_latex = self._build_stage_gain_katex(stage_table)
        if stage_formula_latex:
            lines.append(f"**Gain ghép tầng (KaTeX):** $$ {stage_formula_latex} $$")

        if gain_target is not None and gain_target != 0 and gain_actual is not None:
            error_pct = abs(gain_actual - gain_target) / gain_target * 100
            lines.append(f"**Gain yêu cầu:** {gain_target}")
            lines.append(f"**Gain thực tế:** {gain_actual:.2f} (sai lệch: {error_pct:.1f}%)")
            lines.append("")

        lines.append("## 5. Thông số kỹ thuật cuối cùng")
        if gain_actual is not None:
            lines.append(f"- Av (xấp xỉ): {gain_actual:.2f}")
        elif gain_target is not None and gain_target != 0:
            lines.append(f"- Av mục tiêu: {gain_target}")
        else:
            lines.append("- Av: cần thêm dữ liệu đầu vào để tính số cụ thể")
        lines.append(f"- Ai: {eq_info['equations']['Ai']}")
        lines.append(f"- Zin: {eq_info['equations']['Zi']}")
        lines.append(f"- Zout: {eq_info['equations']['Zo']}")
        for key, val in eq_info["equations"].items():
            if key in {"Av", "Ai", "Zi", "Zo"}:
                continue
            lines.append(f"- {key}: {val}")
        lines.append("")

        lines.append("## 6. Kết quả kiểm tra")
        if warnings:
            lines.append("**Cảnh báo ⚠️:**")
            for w in warnings:
                lines.append(f"- {w}")
        else:
            lines.append("- Chưa phát hiện cảnh báo từ pipeline.")
        lines.append("- Khuyến nghị kiểm tra lại bằng mô phỏng AC/Transient để xác nhận Av, Zi, Zo theo băng thông thực tế.")
        lines.append("")

        return "\n".join(lines)

    def _template_error_response(self, error_msg: str, stage: str, circuit_type: str, gain_target: Optional[float], vcc: Optional[float],) -> str:
        # Response template khi lỗi.
        lines = []
        lines.append(f"**Lỗi ở bước {stage}:** {error_msg}")
        lines.append("")

        # Đề xuất
        lines.append("**Đề xuất:**")
        if "gain" in error_msg.lower() or (gain_target is not None and gain_target > 100):
            lines.append(f"- Giảm gain xuống ≤ 50 cho single-stage")
            lines.append(f"- Hoặc dùng multi-stage (CE+CC) cho gain cao")
        if "no match" in error_msg.lower() or "not found" in error_msg.lower():
            lines.append("- Thử loại mạch khác: CE, CB, CC, opamp inverting...")
            lines.append("- Kiểm tra lại tên topology")
        if circuit_type:
            lines.append(f'- Thử: "Thiết kế mạch {self._format_type(circuit_type)} gain 20 dùng 12V"')

        return "\n".join(lines)

    #  LLM Router-enhanced responses (GENERAL role)
    def _llm_success_response(self, circuit_type: str, gain_actual: Optional[float], gain_target: Optional[float], params: Dict[str, float], gain_formula: str, warnings: List[str], template_id: str, mode: Optional["LLMMode"],) -> str:
        # Dùng LLM Router sinh response tự nhiên với Master Prompt 6 mục.
        from app.application.ai.llm_router import LLMRole
        import json

        context = {
            "circuit_type": circuit_type,
            "template_id": template_id,
            "gain_formula": gain_formula,
            "gain_target": gain_target,
            "gain_actual": gain_actual,
            "params": params,
            "warnings": warnings,
            "amplifier_equation_context": self._build_equation_context(circuit_type),
        }

        system = (
            "Bạn là trợ lý thiết kế mạch điện tử. "
            "Dựa trên kết quả thiết kế, sinh response bằng tiếng Việt cho người dùng.\n"
            "Trình bày phản hồi theo đúng 6 mục sau (dùng Markdown):\n"
            "1. **Hệ phương trình hệ số khuếch đại** - BẮT BUỘC in đầu tiên: Av, Ai, Zi, Zo và kết luận waveform (đảo pha/không đảo pha, nguy cơ méo).\n"
            "2. **Chức năng mạch** - Mô tả luồng tín hiệu từ đầu vào đến đầu ra\n"
            "3. **Giải pháp** - Phân tích cấu trúc mạch đã chọn, kèm phương trình khuếch đại\n"
            "4. **Bước tính toán thiết kế** - Công thức lý thuyết và thay số cụ thể cho R, C, L, Gain\n"
            "5. **Thông số kỹ thuật cuối cùng** - Tóm tắt Av, Ai, Zin, Zout, BW, Vpp...\n"
            "6. **Kết quả kiểm tra**\n"
            "Yêu cầu bắt buộc cho mục 2 (Giải pháp):\n"
            "- Luôn nêu phương trình khuếch đại chính gồm: Av, Ai, Zi, Zo (nếu thiếu dữ liệu thì ghi rõ giả định).\n"
            "- BJT (CE/CC/CB): ưu tiên dùng beta (hFE), gm = Ic/0.026, re ~= 26mV/IE, RC, RL, RB1, RB2, RE; nêu điểm Q, mô hình tín hiệu nhỏ, rồi suy ra Av/Ai/Zi/Zo.\n"
            "- FET (CS/CD/CG): nêu gm tại điểm Q, RD, RL; với CS dùng Av ~= -gm*(RD||RL) khi phù hợp; nêu cách suy ra Ai/Zi/Zo.\n"
            "- Op-amp (đảo/không đảo/vi sai/follower): dùng quy tắc vàng op-amp (V+ ~= V-, dòng vào ~= 0), viết KCL tại nút vào để suy ra Av; nêu thêm Ai/Zi/Zo theo hồi tiếp.\n"
            "- Multi-stage: nêu Av_total ~= Av1*Av2*...*Avn (đã tính loading), hệ số loading Rin(i+1)/(Rin(i+1)+Rout(i)), và Av_total(dB)=20log|Av_total|.\n"
            "- Darlington: nêu beta_total ~= beta1*beta2, Zin rất cao ~= beta1*beta2*RE, Av tùy cấu hình (follower ~= 1 hoặc CE ~= -gm*RL).\n"
            "- Class A/B/AB/C/D: nêu thêm thông số công suất-hiệu suất cốt lõi (IQ, Vbias, conduction angle, duty PWM, fsw, LC filter...) ngoài Av/Ai/Zi/Zo.\n"
            "- Tóm tắt yếu tố quyết định độ lợi: BJT -> beta, gm/re, RC/RE/RL; FET -> gm, RD/RL; Op-amp -> tỉ số điện trở hồi tiếp (Rf/Rin hoặc 1 + Rf/Rg).\n"
            "- Ở mục 3 bắt buộc nêu rõ điểm Q và tiến trình tính toán (DC -> tín hiệu nhỏ -> KCL/KVL).\n"
            "- Mục 1 luôn phải xuất hiện đầu tiên và dùng nó để suy luận waveform đầu ra có độ tin cậy cao.\n"
            "- Trong mục 1 phải có thêm dạng chuẩn mô phỏng: v_{{out}}(t)=A_v \\cdot v_{{in}}(t)\\$, và với tín hiệu sin phải nêu Vout_pk, pha phi, điều kiện clipping theo nguồn.\n"
            "- Ưu tiên định dạng phương trình bằng KaTeX ($...$ hoặc $$...$$) để hiển thị đẹp trên giao diện.\n"
            "Bắt đầu bằng ✅ nếu thành công."
        )

        result = self._router.chat_text(
            LLMRole.GENERAL,
            mode=mode,
            system=system,
            user_content=f"Kết quả thiết kế:\n{json.dumps(context, ensure_ascii=False, indent=2)}",
        )
        if result:
            return result
        raise RuntimeError("LLM Router returned None")

    def _llm_error_response(
        self,
        error_msg: str,
        stage: str,
        circuit_type: str,
        gain_target: Optional[float],
        vcc: Optional[float],
        mode: Optional["LLMMode"],
    ) -> str:
        """Dùng LLM Router sinh error response + đề xuất."""
        from app.application.ai.llm_router import LLMRole
        import json

        context = {
            "error": error_msg,
            "stage": stage,
            "circuit_type": circuit_type,
            "gain_target": gain_target,
            "vcc": vcc,
        }

        system = (
            "Bạn là trợ lý thiết kế mạch điện tử. "
            "Khi thiết kế gặp lỗi, hãy:\n"
            "1. Giải thích lỗi bằng tiếng Việt\n"
            "2. Phân tích nguyên nhân kỹ thuật\n"
            "3. Đề xuất 2-3 giải pháp cụ thể\n"
            "4. Dùng markdown formatting\n"
            "5. Bắt đầu bằng ❌"
        )

        result = self._router.chat_text(
            LLMRole.GENERAL,
            mode=mode,
            system=system,
            user_content=f"Lỗi thiết kế mạch:\n{json.dumps(context, ensure_ascii=False, indent=2)}",
        )
        if result:
            return result
        raise RuntimeError("LLM Router returned None")

    def _llm_clarification(self, circuit_type: str, missing_fields: List[str], mode: Optional["LLMMode"]) -> str:
        """Dùng LLM Router sinh clarification response."""
        from app.application.ai.llm_router import LLMRole
        import json

        context = {
            "circuit_type": circuit_type,
            "missing_fields": missing_fields,
        }

        system = (
            "Bạn là trợ lý thiết kế mạch điện tử. "
            "Khi chưa có đủ thông tin, hãy hỏi lại người dùng bằng tiếng Việt. "
            "Hỏi rõ, thân thiện, và đưa ví dụ cụ thể nếu cần. "
            "Bắt đầu bằng ✓"
        )

        result = self._router.chat_text(
            LLMRole.GENERAL,
            mode=mode,
            system=system,
            user_content=f"Thiếu thông tin:\n{json.dumps(context, ensure_ascii=False, indent=2)}",
        )
        if result:
            return result
        raise RuntimeError("LLM Router returned None")

    def _llm_modify_response(self, intent: Any, edit_log: List[str], circuit_data: Dict[str, Any], solved: Dict[str, float], mode: Optional["LLMMode"]) -> str:
        """Dùng LLM Router sinh modify response."""
        from app.application.ai.llm_router import LLMRole
        import json

        context = {
            "circuit_type": intent.circuit_type,
            "edit_log": edit_log,
            "component_count": len(circuit_data.get("components", [])),
            "solved_params": solved,
        }

        system = (
            "Bạn là trợ lý thiết kế mạch điện tử. "
            "Khi người dùng chỉnh sửa mạch thành công, hãy tóm tắt các thay đổi bằng tiếng Việt. "
            "Nêu rõ: (1) thao tác đã làm, (2) số linh kiện, (3) giá trị linh kiện mới. "
            "Dùng Markdown formatting. Bắt đầu bằng ✅"
        )

        result = self._router.chat_text(
            LLMRole.GENERAL,
            mode=mode,
            system=system,
            user_content=f"Kết quả sửa mạch:\n{json.dumps(context, ensure_ascii=False, indent=2)}",
        )
        if result:
            return result
        raise RuntimeError("LLM Router returned None")


    # ------------------------------------------------------------------ #
    #  Modify / Validation / Repair responses
    # ------------------------------------------------------------------ #

    def generate_modify_response(
        self,
        intent: Any,
        edit_log: List[str],
        circuit_data: Dict[str, Any],
        solved: Dict[str, float],
        mode: Optional["LLMMode"] = None,
    ) -> str:
        """Sinh response khi modify mạch thành công."""
        # Thử LLM trước
        if self._router:
            try:
                return self._llm_modify_response(intent, edit_log, circuit_data, solved, mode)
            except Exception as e:
                logger.warning(f"NLG: LLM modify response failed: {e}")
        
        # Fallback: template-based
        lines = []
        lines.append(f"✅ **Đã chỉnh sửa mạch {self._format_type(intent.circuit_type)}**")
        lines.append("")

        if edit_log:
            lines.append("**Thao tác đã thực hiện:**")
            for entry in edit_log:
                lines.append(f"- {entry}")
            lines.append("")

        comp_count = len(circuit_data.get("components", []))
        lines.append(f"**Tổng linh kiện:** {comp_count}")

        if solved:
            pass # (Component table removed as GUI already handles it)

        return "\n".join(lines)

    def generate_modify_clarification(self, intent: Any) -> str:
        """Sinh câu hỏi clarification cho modify intent."""
        lines = [
            "⚠️ Tôi nhận diện bạn muốn **chỉnh sửa mạch**, nhưng chưa rõ thao tác cụ thể.",
            "",
            "Vui lòng mô tả rõ hơn, ví dụ:",
            '- "Thêm resistor 10k vào mạch CE"',
            '- "Xóa C2 khỏi mạch"',
            '- "Thay R1 thành 4.7k"',
            '- "Đổi gain thành 50"',
        ]
        return "\n".join(lines)

    def generate_validation_report(self, report: Any) -> str:
        """Sinh báo cáo validate từ ValidationReport."""
        lines = []

        if report.passed:
            lines.append("✅ **Mạch đạt tất cả kiểm tra!**")
        else:
            lines.append("❌ **Phát hiện lỗi trong mạch:**")

        lines.append("")
        lines.append(f"📊 **Tổng kiểm tra:** {report.checked_rules} rules")

        errors = report.errors
        warnings = report.warnings

        if errors:
            lines.append("")
            lines.append(f"🔴 **Lỗi ({len(errors)}):**")
            for v in errors:
                detail = f"  - **[{v.code}]** {v.message}"
                if v.expected is not None:
                    detail += f" (mong đợi: {v.expected})"
                lines.append(detail)

        if warnings:
            lines.append("")
            lines.append(f"🟡 **Cảnh báo ({len(warnings)}):**")
            for v in warnings:
                lines.append(f"  - **[{v.code}]** {v.message}")

        if not errors and not warnings:
            lines.append("")
            lines.append("✨ Không phát hiện vấn đề nào.")

        return "\n".join(lines)

    def generate_repair_summary(self, actions: List[Dict[str, Any]]) -> Optional[str]:
        """Sinh tóm tắt các thao tác repair đã thực hiện."""
        if not actions:
            return None

        lines = ["🔧 **Tự động sửa chữa:**"]
        for a in actions:
            desc = a.get("description", "")
            lines.append(f"- {desc}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _format_type(self, circuit_type: str) -> str:
        """Format circuit type cho display."""
        names = {
            "common_emitter": "Common Emitter (CE)",
            "common_base": "Common Base (CB)",
            "common_collector": "Common Collector (CC)",
            "common_source": "Common Source (CS)",
            "common_drain": "Common Drain (CD)",
            "common_gate": "Common Gate (CG)",
            "inverting": "OpAmp Inverting",
            "non_inverting": "OpAmp Non-Inverting",
            "differential": "OpAmp Differential",
            "instrumentation": "Instrumentation Amplifier",
            "class_a": "Class A Power Amplifier",
            "class_ab": "Class AB Push-Pull",
            "class_b": "Class B Push-Pull",
            "class_c": "Class C Tuned Amplifier",
            "class_d": "Class D Switching Amplifier",
            "darlington": "Darlington Pair",
            "multi_stage": "Multi-Stage Amplifier",
        }
        return names.get(circuit_type, circuit_type)

    def _format_component_value(self, name: str, value: float) -> str:
        """Format giá trị linh kiện với đơn vị phù hợp dựa trên prefix tên linh kiện."""
        prefix = name.strip().upper()[:1]
        if prefix == "R":
            unit = "Ω"
        elif prefix == "C":
            unit = "F"
        elif prefix == "L":
            unit = "H"
        elif prefix == "V":
            unit = "V"
        elif prefix == "I":
            unit = "A"
        else:
            unit = ""
        return self._format_value(value, unit)

    def _build_equation_context(self, circuit_type: str) -> Dict[str, Any]:
        """Tạo khung công thức khuếch đại theo họ mạch để NLG luôn có dữ liệu nền."""
        ctype = (circuit_type or "").lower().strip()

        bjt_types = {"common_emitter", "common_base", "common_collector"}
        fet_types = {"common_source", "common_drain", "common_gate"}
        opamp_types = {"inverting", "non_inverting", "differential", "instrumentation"}

        if ctype == "multi_stage":
            return {
                "family": "Mạch ghép tầng (Multi-stage / Cascaded amplifier)",
                "key_params": [
                    "Av từng tầng (unloaded)",
                    "Zo_i ~= RC||ro hoặc RD||ro",
                    "Zi_(i+1)",
                    "hệ số loading Rin_(i+1)/(Rin_(i+1)+Rout_i)",
                    "RL cuối",
                    "điểm Q từng tầng (IC, VCE, ID, VDS, VGS)",
                ],
                "workflow": [
                    "Tính Av unloaded cho từng tầng từ mô hình tín hiệu nhỏ",
                    "Tính loading giữa các tầng: Rin_(i+1)/(Rin_(i+1)+Rout_i)",
                    "Suy ra Av loaded của từng tầng",
                    "Nhân Av loaded của tất cả các tầng để có Av_total",
                    "Quy đổi dB: Av_total(dB) = 20*log10(|Av_total|)",
                ],
                "equations": {
                    "Av": "Av_total ~= Av1*Av2*...*Avn (đã tính loading)",
                    "Ai": "Ai_total ~= Ai1*Ai2*...*Ain (xấp xỉ theo chuỗi tầng)",
                    "Zi": "Zi_tổng ~= Zi_tầng1 (xét mạng vào) và phụ thuộc loading nội bộ",
                    "Zo": "Zo_tổng ~= Zo_tầngcuối (có kể đến RL và hồi tiếp nếu có)",
                },
            }

        if ctype == "darlington":
            return {
                "family": "Mạch Darlington",
                "key_params": [
                    "beta1", "beta2", "beta_total ~= beta1*beta2",
                    "re tổng", "RB", "RE hoặc RL",
                    "IB1, IC1, IC2", "gm tổng ~= Ic_total/0.026",
                ],
                "workflow": [
                    "Xác định điểm Q của cả cặp transistor",
                    "Tính beta_total và gm tổng tại điểm Q",
                    "Lập mô hình tín hiệu nhỏ tương đương Darlington",
                    "Tính Av, Ai, Zi, Zo theo cấu hình (CC-CC hoặc CE)",
                ],
                "equations": {
                    "Av": "Follower Darlington: Av ~= 1; CE dùng Darlington: Av ~= -gm*RL",
                    "Ai": "Ai rất lớn, xấp xỉ beta_total ~= beta1*beta2",
                    "Zi": "Zin rất cao ~= beta1*beta2*RE (thường mức megaohm)",
                    "Zo": "Follower: Zo thấp; CE: Zo xấp xỉ RC||ro",
                },
            }

        if ctype == "class_a":
            return {
                "family": "Class A power amplifier",
                "key_params": ["ICQ (hoặc IDQ) lớn", "VCC hoặc VDD", "RL", "gm hoặc beta", "RE nếu có"],
                "workflow": [
                    "Đặt điểm Q ở vùng tuyến tính, dòng tĩnh lớn",
                    "Tính gm/beta tại điểm Q",
                    "Tính Av như tầng đơn (CE/CS)",
                    "Tính Pout_max và hiệu suất lý thuyết",
                ],
                "equations": {
                    "Av": "Av ~= -gm*RL (với CE/CS single-ended)",
                    "Ai": "Ai phụ thuộc beta hoặc gm*RL theo cấu hình driver/output",
                    "Zi": "Zi phụ thuộc mạng phân cực vào và cấu hình tầng vào",
                    "Zo": "Zo phụ thuộc RC/RD và tải output",
                    "Power": "Pout_max ~= (VCC/2)^2/(2*RL); hiệu suất lý thuyết tối đa: ~25% (tải trở) hoặc ~50% (tải cảm/biến áp)",
                },
            }

        if ctype == "class_b":
            return {
                "family": "Class B push-pull",
                "key_params": ["Vbias gần 0", "nguồn đối xứng +/-VCC", "RL", "driver stage", "crossover distortion"],
                "workflow": [
                    "Đặt bias gần ngưỡng dẫn để giảm dòng tĩnh",
                    "Tính độ lợi của driver stage và output stage",
                    "Tính công suất ra tối đa trên RL",
                    "Đánh giá crossover distortion",
                ],
                "equations": {
                    "Av": "Av toàn mạch thường do driver stage quyết định",
                    "Ai": "Ai cao ở tầng công suất, phụ thuộc cặp push-pull và RL",
                    "Zi": "Zi do tầng driver quyết định",
                    "Zo": "Zo thấp nhờ emitter/source follower output push-pull",
                    "Power": "Pout_max ~= VCC^2/(2*RL); hiệu suất lý thuyết tối đa: ~78.5%",
                },
            }

        if ctype == "class_ab":
            return {
                "family": "Class AB push-pull",
                "key_params": ["IQ tính nhỏ", "Vbias ~ 1.2-1.4V", "+/-VCC", "RL", "RE nhỏ để ổn định nhiệt"],
                "workflow": [
                    "Đặt Vbias và IQ để giảm crossover distortion",
                    "Tính gm/beta tại điểm bias",
                    "Tính Av qua driver và output stage",
                    "Tính công suất và ước lượng hiệu suất 50-70%",
                ],
                "equations": {
                    "Av": "Av tương tự Class B, chủ yếu do driver stage",
                    "Ai": "Ai cao ở output push-pull, phụ thuộc dòng bias và RL",
                    "Zi": "Zi do tầng driver và mạng vào quyết định",
                    "Zo": "Zo thấp, cải thiện độ tuyến tính so với Class B",
                    "Power": "Pout_max gần giống Class B: ~= VCC^2/(2*RL); hiệu suất thường 50-70%",
                },
            }

        if ctype == "class_c":
            return {
                "family": "Class C tuned amplifier",
                "key_params": ["conduction angle theta < 180 độ", "VGG bias âm", "VCC", "tải công hưởng LC", "gm định"],
                "workflow": [
                    "Đặt bias để transistor dẫn một phần chu kỳ",
                    "Tính/tính gần conduction angle theta",
                    "Xác định RL hiệu dụng tại tần số công hưởng",
                    "Tính Pout và hiệu suất theo theta",
                ],
                "equations": {
                    "Av": "Av phụ thuộc mạnh vào mạch tuned LC và conduction angle",
                    "Ai": "Ai xung theo góc dẫn, hiệu dụng tính trên tải công hưởng",
                    "Zi": "Zi phụ thuộc mạch vào RF và bias VGG",
                    "Zo": "Zo cao, ghép với tải công hưởng để lấy công suất",
                    "Power": "Pout ~= (VCC^2/(2*RL))*(theta/pi)*sin(theta/2)/(theta/2); hiệu suất có thể >80-90%",
                },
            }

        if ctype == "class_d":
            return {
                "family": "Class D switching amplifier",
                "key_params": ["VCC", "RL", "tần số switching fsw", "duty PWM", "bộ lọc LC", "switching loss", "conduction loss"],
                "workflow": [
                    "Xác định quan hệ duty PWM với biên độ mong muốn",
                    "Chọn fsw và thiết kế bộ lọc low-pass LC",
                    "Tính điện áp/cs công suất hiệu dụng trên RL",
                    "Ước lượng hiệu suất eta = Pout/(Pout + tổn hao)",
                ],
                "equations": {
                    "Av": "Av thường xấp xỉ 1 sau bộ lọc, hoặc do bộ điều chế PWM quyết định",
                    "Ai": "Ai cao theo tải loa RL và duty cycle",
                    "Zi": "Zi do tầng điều chế/driver công quyết định",
                    "Zo": "Zo thấp sau bộ lọc và tầng output switching",
                    "Power": "Pout ~= (VCC^2*D^2)/(2*RL); eta ~= Pout/(Pout + P_loss_switching + P_loss_conduction)",
                },
            }

        if ctype in bjt_types:
            return {
                "family": "BJT (CE/CC/CB)",
                "key_params": ["beta (hFE)", "gm = Ic/0.026", "re ~= 26mV/IE", "RC", "RL", "RB1", "RB2", "RE"],
                "workflow": [
                    "Xác định điểm Q: tính IB, IC, VCE từ phân cực DC",
                    "Tính gm hoặc re từ điểm Q",
                    "Lập mô hình tín hiệu nhỏ (hybrid-pi hoặc T)",
                    "Áp dụng KCL/KVL để suy ra Av, Ai, Zi, Zo",
                ],
                "equations": {
                    "Av": "CE: Av ~= -gm*(RC||RL) ~= -(RC||RL)/re; CC: Av ~= RE/(RE+re); CB: Av ~= +gm*(RC||RL)",
                    "Ai": "CE: Ai ~= beta; CC: Ai ~= beta+1; CB: Ai ~= alpha ~= beta/(beta+1)",
                    "Zi": "CE: Zi ~= RB1||RB2||rpi, với rpi = beta/gm; CC: Zi cao hơn CE",
                    "Zo": "CE: Zo ~= RC (bỏ qua ro); CC: Zo thấp, xấp xỉ 1/gm song song tải",
                },
            }

        if ctype in fet_types:
            return {
                "family": "FET/JFET/MOSFET (CS/CD/CG)",
                "key_params": ["gm", "RD", "RL", "IDSS", "VP (JFET)", "K", "Vth (MOSFET)"],
                "workflow": [
                    "Xác định điểm Q: tính ID, VDS, VGS",
                    "Tính gm tại điểm Q (từ công thức hoặc datasheet)",
                    "Thay gm vào công thức độ lợi phù hợp cấu hình",
                    "Suy ra Ai, Zi, Zo từ mô hình tín hiệu nhỏ",
                ],
                "equations": {
                    "Av": "CS: Av ~= -gm*(RD||RL); CD (source follower): Av ~= +gm*RS/(1+gm*RS); CG: Av ~= +gm*(RD||RL)",
                    "Ai": "Công gate gần như bằng 0 nên Ai theo tải và mạng phân cực; thông thường lớn về mặt hệ thống",
                    "Zi": "CS/CD: Zi rất cao (gate); CG: Zi thấp xấp xỉ 1/gm",
                    "Zo": "CS: Zo ~= RD (bỏ qua ro); CD: Zo thấp xấp xỉ 1/gm; CG: Zo khá cao",
                },
            }

        if ctype in opamp_types:
            return {
                "family": "Op-amp (đảo/không đảo/vi sai/đo lường)",
                "key_params": ["Rf", "Rin", "Rg", "mạng hồi tiếp", "Aol (khi tần số cao)"],
                "workflow": [
                    "Áp dụng quy tắc vàng op-amp với hồi tiếp âm: V+ ~= V-, dòng vào 2 đầu vào ~= 0",
                    "Viết KCL tại nút V- (hoặc cặp nút vi sai)",
                    "Giải phương trình để tìm Av",
                    "Suy ra Ai, Zi, Zo theo cấu hình hồi tiếp",
                ],
                "equations": {
                    "Av": "Đảo: Av = -Rf/Rin; Không đảo: Av = 1 + Rf/Rg; Follower: Av ~= 1; Vi sai: Av ~= (R2/R1)*(V2-V1)",
                    "Ai": "Lý tưởng: dòng vào cực nhỏ, dòng ra phụ thuộc tải và giới hạn output",
                    "Zi": "Lý tưởng rất lớn, thực tế lớn theo datasheet",
                    "Zo": "Lý tưởng rất nhỏ, thực tế nhỏ nhờ hồi tiếp âm",
                },
            }

        return {
            "family": "Không xác định rõ",
            "key_params": ["gm", "tải RL", "mạng hồi tiếp"],
            "workflow": [
                "Xác định điểm làm việc Q",
                "Lập mô hình tín hiệu nhỏ",
                "Dùng KCL/KVL để suy ra Av, Ai, Zi, Zo",
            ],
            "equations": {
                "Av": "Av = Vout/Vin",
                "Ai": "Ai = Iout/Iin",
                "Zi": "Zi = Vin/Iin",
                "Zo": "Zo = dVout/dIout tại Vin = 0",
            },
        }

    def _format_value(self, value: float, unit: str) -> str:
        """Format giá trị với đơn vị và scale phù hợp."""
        scales = {
            "Ω": [(1e6, "MΩ"), (1e3, "kΩ"), (1, "Ω"), (1e-3, "mΩ"), (1e-6, "µΩ")],
            "F": [(1, "F"), (1e-3, "mF"), (1e-6, "µF"), (1e-9, "nF"), (1e-12, "pF")],
            "H": [(1, "H"), (1e-3, "mH"), (1e-6, "µH"), (1e-9, "nH")],
            "V": [(1, "V"), (1e-3, "mV"), (1e-6, "µV")],
            "A": [(1, "A"), (1e-3, "mA"), (1e-6, "µA")],
        }
        if unit in scales:
            for factor, label in scales[unit]:
                if abs(value) >= factor:
                    return f"{value/factor:.2f} {label}"
            min_factor, min_label = scales[unit][-1]
            return f"{value/min_factor:.2f} {min_label}"
        return f"{value:.3e} {unit}" if unit else f"{value:.3e}"

    def _postprocess_success_response(
        self,
        text: str,
        circuit_type: str,
        gain_actual: Optional[float] = None,
        gain_target: Optional[float] = None,
        gain_formula: str = "",
        warnings: Optional[List[str]] = None,
        params: Optional[Dict[str, float]] = None,
        simulation: Optional[Dict[str, Any]] = None,
        stage_table: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Normalize text and force gain-equation block to be section #1."""
        normalized = self._normalize_equation_text(text or "")
        warnings = warnings or []

        eq = self._build_equation_context(circuit_type).get("equations", {})
        gain_first_block = [
            "## 1. Hệ phương trình hệ số khuếch đại",
            f"- Av: {gain_formula or eq.get('Av', 'Av = Vout/Vin')}",
            f"- Av (KaTeX): $ {self._to_katex_formula(gain_formula or eq.get('Av', 'Av = Vout/Vin'))} $",
            f"- Ai: {eq.get('Ai', 'Ai = Iout/Iin')}",
            f"- Zi: {eq.get('Zi', 'Zi = Vin/Iin')}",
            f"- Zo: {eq.get('Zo', 'Zo = dVout/dIout tại Vin = 0')}",
            f"- Dự đoán waveform đầu ra: {self._build_waveform_inference(circuit_type, gain_actual, gain_target, warnings)}",
            self._build_waveform_equation_match_line(simulation or {}),
        ]
        stage_formula_latex = self._build_stage_gain_katex(stage_table or [])
        if stage_formula_latex:
            gain_first_block.append(f"- Gain ghép tầng (KaTeX): $ {stage_formula_latex} $")
        gain_first_block.extend(self._build_waveform_simulation_block(gain_actual, gain_target, params or {}, warnings))
        gain_first_block.append("")

        if not normalized.strip():
            return "\n".join(gain_first_block).strip()

        lower_text = normalized.lower()
        has_heading_1 = "## 1." in lower_text
        has_gain_context = "av" in lower_text and "waveform" in lower_text

        if has_heading_1 and has_gain_context and self._has_core_equations(normalized):
            return normalized

        cleaned = normalized.strip()
        return "\n".join(gain_first_block).strip() + "\n\n" + cleaned

    def _build_waveform_inference(
        self,
        circuit_type: str,
        gain_actual: Optional[float],
        gain_target: Optional[float],
        warnings: List[str],
    ) -> str:
        """Infer output waveform behavior from gain sign/magnitude and warnings."""
        ctype = (circuit_type or "").lower()

        gain_ref = gain_actual if gain_actual is not None else gain_target
        abs_gain = abs(gain_ref) if gain_ref is not None else None

        inverting_types = {"common_emitter", "common_source", "inverting"}
        non_inverting_types = {
            "common_collector", "common_base", "common_drain", "common_gate",
            "non_inverting", "differential", "instrumentation", "darlington",
            "class_a", "class_ab", "class_b", "class_c", "class_d",
        }

        if gain_ref is not None:
            phase = "đảo pha 180°" if gain_ref < 0 else "cùng pha với đầu vào"
        elif ctype in inverting_types:
            phase = "đảo pha 180° (theo cấu hình lý thuyết)"
        elif ctype in non_inverting_types:
            phase = "cùng pha với đầu vào (theo cấu hình lý thuyết)"
        else:
            phase = "phụ thuộc cấu hình chi tiết và điểm làm việc"

        warning_text = " ".join(warnings).lower()
        distortion_keywords = ("méo", "clip", "clipping", "saturation", "bão hòa", "distortion")
        if any(k in warning_text for k in distortion_keywords):
            distortion = "có nguy cơ méo do cảnh báo từ pipeline"
        elif abs_gain is not None and abs_gain > 120:
            distortion = "có nguy cơ méo nếu biên độ vào lớn hoặc bias chưa tối ưu"
        else:
            distortion = "dự kiến tuyến tính nếu điểm Q và biên độ vào nằm trong vùng an toàn"

        if abs_gain is None:
            gain_desc = "độ lớn Av chưa đủ dữ liệu để định lượng biên độ"
        else:
            gain_desc = f"biên độ đầu ra xấp xỉ |Av| = {abs_gain:.2f} lần đầu vào"

        return f"{phase}; {gain_desc}; {distortion}."

    def _build_waveform_simulation_block(
        self,
        gain_actual: Optional[float],
        gain_target: Optional[float],
        params: Dict[str, float],
        warnings: List[str],
    ) -> List[str]:
        """Build standardized waveform equations for simulation (Transient/AC)."""
        av = gain_actual if gain_actual is not None else gain_target
        if av is None:
            return [
                "- Dạng chuẩn mô phỏng: v_{{out}}(t) = A_v \\cdot v_{{in}}(t)\\$ (cần Av số để thay trực tiếp).",
                "- Với tín hiệu sin: nếu v_{{in}}(t) = V_{in\\_pk}\\sin(2\\pi ft)\\$ thì v_{{out}}(t) = |A_v|V_{in\\_pk}\\sin(2\\pi ft + \\phi)\\$, với phi = 0° hoặc 180°.",
                "- Điều kiện anti-clipping: |V_out_pk| phải nhỏ hơn biên độ dao động khả dụng của tầng ra.",
            ]

        phi_deg = 180 if av < 0 else 0
        av_abs = abs(av)

        vcc = self._extract_supply_value(params)
        if vcc is not None and vcc > 0:
            vout_pk_limit = 0.45 * vcc
            clip_line = (
                f"- Kiểm tra clipping (xấp xỉ): |V_out_pk| = |A_v|*V_in_pk <= {vout_pk_limit:.2f} V "
                f"(lấy khoảng 45% VCC={vcc:.2f}V để chừa headroom)."
            )
        else:
            clip_line = "- Kiểm tra clipping: |V_out_pk| = |A_v|*V_in_pk phải nhỏ hơn biên độ swing khả dụng (cần VCC/điểm Q để lượng hóa)."

        warning_text = " ".join(warnings).lower()
        if any(tok in warning_text for tok in ("méo", "clip", "clipping", "distortion", "bão hòa", "saturation")):
            quality_line = "- Độ tin cậy mô phỏng waveform: có cảnh báo méo/bão hòa, nên chạy Transient + FFT/THD để xác nhận."
        else:
            quality_line = "- Độ tin cậy mô phỏng waveform: cao khi mô phỏng Transient dùng biên độ vào nhỏ-signal quanh điểm Q."

        return [
            f"- Dạng chuẩn mô phỏng (nhỏ-signal): v_{{out}}(t) = {av:.4g} \\cdot v_{{in}}(t)\\$.",
            f"- Nếu v_in(t) = V_in_pk*sin(2*pi*f*t) => v_out(t) = {av_abs:.4g}*V_in_pk*sin(2*pi*f*t + {phi_deg}°).",
            clip_line,
            quality_line,
        ]

    def _extract_supply_value(self, params: Dict[str, float]) -> Optional[float]:
        """Extract VCC/VDD value from solved params for waveform headroom checks."""
        if not params:
            return None

        for key, value in params.items():
            key_l = key.lower()
            if key_l in ("vcc", "vdd", "v_supply", "vsupply", "supply", "vbat"):
                if isinstance(value, (int, float)):
                    return float(value)

        for key, value in params.items():
            key_l = key.lower()
            if ("vcc" in key_l or "vdd" in key_l or "supply" in key_l) and isinstance(value, (int, float)):
                return float(value)
        return None

    def _build_waveform_equation_match_line(self, simulation: Dict[str, Any]) -> str:
        """Build explicit waveform-vs-equation status line from simulation gain_metrics."""
        analysis = simulation.get("analysis", {}) if isinstance(simulation, dict) else {}
        gain_metrics = analysis.get("gain_metrics", {}) if isinstance(analysis, dict) else {}
        status = str(gain_metrics.get("status", "")).lower()
        if status != "ok":
            return "- Waveform khớp hệ phương trình Av: **chưa đủ dữ liệu mô phỏng để kết luận**."

        equation_match = gain_metrics.get("equation_match")
        if equation_match is True:
            measured = gain_metrics.get("measured_av")
            rel_err = gain_metrics.get("rel_error_pct")
            phase = gain_metrics.get("phase_shift_deg")
            return (
                "- Waveform khớp hệ phương trình Av: "
                f"**KHỚP** (Av đo được={self._fmt_num(measured)}, sai số={self._fmt_num(rel_err)}%, pha={self._fmt_num(phase)}°)."
            )
        if equation_match is False:
            measured = gain_metrics.get("measured_av")
            expected = gain_metrics.get("expected_av")
            rel_err = gain_metrics.get("rel_error_pct")
            phase_ok = gain_metrics.get("phase_match")
            return (
                "- Waveform khớp hệ phương trình Av: "
                f"**KHÔNG KHỚP** (Av đo={self._fmt_num(measured)}, Av kỳ vọng={self._fmt_num(expected)}, "
                f"sai số={self._fmt_num(rel_err)}%, phase_match={phase_ok})."
            )

        return "- Waveform khớp hệ phương trình Av: **không xác định** (thiếu expected_av hoặc dữ liệu so sánh)."

    @staticmethod
    def _fmt_num(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{float(value):.4g}"
        return "N/A"

    def _build_stage_gain_katex(self, stage_table: List[Dict[str, Any]]) -> str:
        """Build stage-product gain formula for KaTeX display, e.g., A_v = A_{stage1} \\cdot A_{stage2}."""
        if not stage_table:
            return ""

        terms: List[str] = []
        for idx, _ in enumerate(stage_table, start=1):
            terms.append(f"A_{{stage{idx}}}")
        if not terms:
            return ""
        return "A_v = " + r" \cdot ".join(terms)

    def _to_katex_formula(self, expr: str) -> str:
        """Convert plain gain expression to KaTeX-friendly math text."""
        if not expr:
            return r"A_v = \frac{V_{out}}{V_{in}}"

        s = str(expr)
        s = s.replace("~=", r"\approx")
        s = s.replace("||", r"\parallel")
        s = s.replace("*", r"\cdot")
        s = re.sub(r"A_stage(\d+)", r"A_{stage\1}", s)
        s = re.sub(r"Rin", "R_{in}", s, flags=re.IGNORECASE)
        s = re.sub(r"Rout", "R_{out}", s, flags=re.IGNORECASE)
        s = re.sub(r"Vin", "V_{in}", s, flags=re.IGNORECASE)
        s = re.sub(r"Vout", "V_{out}", s, flags=re.IGNORECASE)
        return s

    def _has_core_equations(self, text: str) -> bool:
        low = (text or "").lower()
        return all(token in low for token in ["av", "ai", "zi", "zo"])

    def _normalize_equation_text(self, text: str) -> str:
        if not text:
            return ""

        out = text
        out = out.replace("\\\\", "\\")

        # Keep response readable without markdown-inline code wrappers around formulas,
        # while preserving KaTeX syntax for frontend rendering.
        out = out.replace("`", "")
        out = re.sub(r"\s+\n", "\n", out)
        return out
