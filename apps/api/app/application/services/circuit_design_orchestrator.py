from __future__ import annotations

"""Application orchestrator cho pipeline thiet ke mach da tang.

Module nay dieu phoi LLM -> domain validation -> simulation va retry voi feedback.
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from app.application.ai.llm_contracts import (
    ComponentProposalOutputV1,
    build_llm_payload,
    topology_code_to_name,
    topology_name_to_code,
)
from app.domains.validators import ComponentSet, DCBiasValidator
from app.infrastructure.simulation import NgspiceRunner, SimulationConfig

if TYPE_CHECKING:
    from app.application.ai.llm_router import LLMMode, LLMRole
    from app.application.ai.nlu_service import CircuitIntent
    from app.infrastructure.db.feedback_store import FeedbackStore

logger = logging.getLogger(__name__)


@dataclass
class DesignResult:
    """Ket qua cuoi cung cua pipeline thiet ke."""

    success: bool
    components: Optional["ComponentSet"] = None
    waveform: Optional[Dict] = None
    dc_metrics: Optional[Dict] = None
    sim_metrics: Optional[Dict] = None
    attempts: int = 0
    feedback_history: List[Dict] = field(default_factory=list)
    error_message: str = ""

    def to_dict(self) -> dict:
        """Chuyen ket qua thanh dict de tra API/log."""
        return {
            "success": self.success,
            "components": self.components.to_dict() if self.components else None,
            "waveform": self.waveform or {},
            "dc_metrics": self.dc_metrics or {},
            "sim_metrics": self.sim_metrics or {},
            "attempts": self.attempts,
            "feedback_history": self.feedback_history,
            "error_message": self.error_message,
        }


class CircuitDesignOrchestrator:
    """Dieu phoi pipeline ma khong chua business rule vat ly."""

    MAX_RETRY: int = 3

    def __init__(
        self,
        llm_router,
        dc_validator: DCBiasValidator,
        ngspice_runner: NgspiceRunner,
        feedback_store: Optional["FeedbackStore"] = None,
    ) -> None:
        self.llm_router = llm_router
        self.dc_validator = dc_validator
        self.ngspice_runner = ngspice_runner
        self.feedback_store = feedback_store

    def design(
        self,
        intent: "CircuitIntent",
        mode: Optional["LLMMode"] = None,
    ) -> DesignResult:
        """Chay vong lap propose -> domain check -> sim check toi da MAX_RETRY."""
        feedback_history: List[Dict] = []
        last_error = ""

        for attempt in range(1, self.MAX_RETRY + 1):
            logger.info("Design attempt %s/%s", attempt, self.MAX_RETRY)

            components = self._propose_components(intent=intent, feedback_history=feedback_history, mode=mode)
            if components is None:
                last_error = "LLM khong tra ve ComponentSet hop le"
                feedback_history.append(
                    {
                        "attempt": attempt,
                        "type": "llm_error",
                        "errors": [last_error],
                        "suggestions": ["Tra ve JSON hop le voi du key R1,R2,RC,RE,VCC,beta,topology"],
                    }
                )
                continue

            dc_result = self.dc_validator.validate_by_topology(components, intent.gain_target)
            if not dc_result.passed:
                last_error = "Domain validation failed"
                feedback_history.append(
                    {
                        "attempt": attempt,
                        "type": "domain_error",
                        "errors": dc_result.errors,
                        "suggestions": dc_result.suggestions,
                        "metrics": dc_result.metrics,
                    }
                )
                continue

            sim_config = self._build_sim_config(intent)
            sim_result = self.ngspice_runner.run(
                components=components,
                topology=components.topology or intent.topology,
                gain_target=intent.gain_target,
                sim_config=sim_config,
            )

            if not sim_result.passed:
                # Graceful degradation: nếu thiếu ngspice thi skip sim check.
                ngspice_missing = any("Ngspice not available" in err for err in sim_result.errors)
                if ngspice_missing:
                    logger.warning("Ngspice unavailable, skip sim check va tra ket qua sau domain pass")
                    result = DesignResult(
                        success=True,
                        components=components,
                        waveform={},
                        dc_metrics=dc_result.metrics,
                        sim_metrics={"simulation_skipped": 1.0},
                        attempts=attempt,
                        feedback_history=feedback_history,
                        error_message="",
                    )
                    self._save_feedback_session(intent=intent, result=result)
                    return result

                last_error = "Simulation validation failed"
                feedback_history.append(
                    {
                        "attempt": attempt,
                        "type": "sim_error",
                        "errors": sim_result.errors,
                        "suggestions": sim_result.suggestions,
                        "metrics": sim_result.metrics,
                    }
                )
                continue

            result = DesignResult(
                success=True,
                components=components,
                waveform=sim_result.waveform_data,
                dc_metrics=dc_result.metrics,
                sim_metrics=sim_result.metrics,
                attempts=attempt,
                feedback_history=feedback_history,
                error_message="",
            )
            self._save_feedback_session(intent=intent, result=result)
            return result

        result = DesignResult(
            success=False,
            components=None,
            waveform=None,
            dc_metrics=None,
            sim_metrics=None,
            attempts=self.MAX_RETRY,
            feedback_history=feedback_history,
            error_message=last_error or "Khong tim duoc bo linh kien hop le sau nhieu lan retry",
        )
        self._save_feedback_session(intent=intent, result=result)
        return result

    def _propose_components(
        self,
        intent: "CircuitIntent",
        feedback_history: List[Dict],
        mode: Optional["LLMMode"] = None,
    ) -> Optional["ComponentSet"]:
        """Goi LLM de de xuat bo linh kien va parse ve ComponentSet."""
        from app.application.ai.llm_router import LLMRole

        system_prompt = self._build_system_prompt_for_components()
        user_payload = self._build_user_payload(intent=intent, feedback_history=feedback_history)

        role: "LLMRole" = getattr(LLMRole, "DESIGN", LLMRole.GENERAL)
        response = self.llm_router.chat_json(
            role,
            mode=mode,
            system=system_prompt,
            user_content=user_payload,
            response_model=ComponentProposalOutputV1,
            max_schema_retries=2,
        )

        if not response:
            logger.warning("LLM response is empty")
            return None

        try:
            payload = ComponentProposalOutputV1.model_validate(response)
        except Exception as exc:
            logger.warning("Component schema validation failed: %s", exc)
            return None

        topology_name = topology_code_to_name(payload.tp)

        try:
            components = ComponentSet(
                R1=float(payload.r1),
                R2=float(payload.r2),
                RC=float(payload.rc),
                RE=float(payload.re),
                VCC=float(payload.v),
                beta=float(payload.b),
                topology=topology_name if topology_name != "unknown" else (intent.topology or "common_emitter"),
            )
            return components
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning("Parse ComponentSet failed: %s", exc)
            return None

    def _build_system_prompt_for_components(self) -> str:
        """Sinh system prompt mo ta schema JSON component output."""
        return (
            "Ban la ky su analog design. Tra ve duy nhat JSON theo schema cmp.v1. "
            "Khong markdown, khong giai thich.\n"
            "Schema: {\"sv\":\"cmp.v1\",\"tp\":\"CE|CB|CC|CS|CD|CG|INV|NON|DIF|INA|CLA|CLAB|CLB|CLC|CLD|DAR|MST|UNK\","
            "\"r1\":number,\"r2\":number,\"rc\":number,\"re\":number,\"v\":number,\"b\":number}.\n"
            "Rang buoc: r1,r2>=1000; rc>=100; re>=0; v>0; b trong [50,300]."
        )

    def _build_user_payload(self, intent: "CircuitIntent", feedback_history: List[Dict]) -> Dict[str, object]:
        """Sinh payload JSON tu intent va lich su loi de huong LLM retry."""
        topology = topology_name_to_code(intent.topology or "common_emitter").value
        gain = intent.gain_target if intent.gain_target is not None else None
        vcc = intent.vcc if intent.vcc is not None else 12.0
        freq = intent.frequency if intent.frequency is not None else 1000.0

        return build_llm_payload(
            task="cmp.propose.v1",
            input_data={
                "it": {
                    "tp": topology,
                    "gn": gain,
                    "vc": vcc,
                    "fq": freq,
                },
                "fb": feedback_history,
            },
            output_format="json",
        )

    def _build_sim_config(self, intent: "CircuitIntent") -> "SimulationConfig":
        """Tao config mo phong tu intent de dung cho ngspice runner."""
        frequency = intent.frequency if intent.frequency and intent.frequency > 0 else 1000.0
        vcc = intent.vcc if intent.vcc and intent.vcc > 0 else 12.0
        vin_amp = min(max(vcc * 0.001, 0.005), 0.05)
        return SimulationConfig(
            vin_amplitude=vin_amp,
            frequency=frequency,
            duration_cycles=5,
            step_size_factor=0.01,
        )

    def _save_feedback_session(self, intent: "CircuitIntent", result: DesignResult) -> None:
        """Luu session vao store neu duoc cung cap."""
        if self.feedback_store is None:
            return

        try:
            self.feedback_store.save_session(
                session_id=str(uuid.uuid4()),
                intent=intent,
                result=result,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("Save feedback session failed: %s", exc)
