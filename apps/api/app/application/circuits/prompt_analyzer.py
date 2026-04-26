"""Prompt analyzer for Circuits flow.

Detailed input-output flow:
1. Input source:
    - Called by routes:
      - POST /api/circuits/generate/from-prompt
      - POST /api/circuits/analyze-prompt
    - Receives:
      - prompt: natural language request
      - parameters: optional explicit overrides from client

2. Parsing stage:
    - Uses NLUService.understand(prompt) to extract intent fields.

3. Mapping stage:
    - Maps intent.circuit_type to template_id via CIRCUIT_TYPE_TO_TEMPLATE_ID.

4. Merge stage:
    - Extracts parameters from intent (gain/vcc/frequency).
    - Merges extracted params with caller-provided parameters.
    - Caller-provided parameters override extracted values on conflicts.

5. Validation stage:
    - Checks required parameters by template via TEMPLATE_REQUIREMENTS.
    - Builds missing parameter list.

6. Classification stage:
    - CLEAR: template is known, confidence >= 0.3, no required params missing.
    - AMBIGUOUS: template known but required params are missing.
    - INVALID: template unknown or low confidence.

7. Output contract:
    - PromptAnalysis:
      - clarity
      - template_id (optional)
      - parameters (merged)
      - questions (clarification list)
      - confidence
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from app.application.ai.nlu_service import NLUService


class PromptClarity(Enum):
    """Clarity level of user prompt."""

    CLEAR = "clear"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


@dataclass
class ClarifyingQuestion:
    """A question to ask the user for clarification."""

    field: str
    question: str
    suggestions: List[str]
    required: bool = True


@dataclass
class PromptAnalysis:
    """Result of analyzing a user prompt."""

    clarity: PromptClarity
    template_id: Optional[str] = None
    parameters: Dict[str, Any] = None
    questions: List[ClarifyingQuestion] = None
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if self.parameters is None:
            self.parameters = {}
        if self.questions is None:
            self.questions = []


class PromptAnalyzer:
    """Analyze prompt readiness for template-based circuit generation.

    This class does not generate circuits directly.
    It only classifies prompt clarity and returns normalized analysis output
    for route handlers to decide generate vs clarification.
    """

    CIRCUIT_TYPE_TO_TEMPLATE_ID: Dict[str, str] = {
        "common_emitter": "bjt_common_emitter",
        "common_collector": "bjt_common_collector",
        "common_base": "bjt_common_base",
        "common_source": "mosfet_common_source",
        "common_drain": "mosfet_common_drain",
        "common_gate": "mosfet_common_gate",
        "inverting": "opamp_inverting",
        "non_inverting": "opamp_non_inverting",
        "differential": "opamp_differential",
        "instrumentation": "opamp_instrumentation",
        "class_a": "bjt_class_a",
        "class_ab": "bjt_class_ab",
        "class_b": "bjt_class_b",
        "darlington": "bjt_darlington",
        "multi_stage": "bjt_multi_stage",
    }

    TEMPLATE_REQUIREMENTS = {
        "bjt_common_emitter": ["vcc", "gain"],
        "bjt_common_collector": ["vcc", "gain"],
        "bjt_common_base": ["vcc", "gain"],
        "opamp_inverting": ["gain"],
        "opamp_non_inverting": ["gain"],
        "opamp_differential": ["gain"],
    }

    def analyze(self, prompt: str, parameters: Optional[Dict[str, Any]] = None) -> PromptAnalysis:
        """Run prompt analysis pipeline and return normalized PromptAnalysis.

        Stage-by-stage behavior:
        1. Parse prompt with NLUService -> intent
        2. Resolve template_id from intent.circuit_type
        3. Extract parameters from intent
        4. Merge with caller parameters (caller wins)
        5. Check required parameters for selected template
        6. Return PromptAnalysis with clarity clear/ambiguous/invalid

        Args:
            prompt: User natural language request.
            parameters: Optional explicit parameter overrides from caller.

        Returns:
            PromptAnalysis used by API routes.
        """
        if parameters is None:
            parameters = {}

        try:
            intent = NLUService().understand(prompt)
        except Exception:
            return PromptAnalysis(
                clarity=PromptClarity.INVALID,
                confidence=0.0,
                questions=self._generate_questions("", ["topology"]),
            )

        template_id = None
        if intent.circuit_type and intent.circuit_type != "unknown":
            template_id = self.CIRCUIT_TYPE_TO_TEMPLATE_ID.get(intent.circuit_type, intent.circuit_type)

        extracted = self._extract_parameters_from_intent(intent)
        all_params = {**extracted, **parameters}

        if not template_id or intent.confidence < 0.3:
            return PromptAnalysis(
                clarity=PromptClarity.INVALID,
                confidence=intent.confidence,
                parameters=all_params,
                questions=self._generate_questions("", ["topology"]),
            )

        required_params = self.TEMPLATE_REQUIREMENTS.get(template_id, ["gain"])
        missing_params = [name for name in required_params if all_params.get(name) is None]

        if not missing_params:
            return PromptAnalysis(
                clarity=PromptClarity.CLEAR,
                template_id=template_id,
                parameters=all_params,
                confidence=intent.confidence,
            )

        return PromptAnalysis(
            clarity=PromptClarity.AMBIGUOUS,
            template_id=template_id,
            parameters=all_params,
            questions=self._generate_questions(template_id, missing_params),
            confidence=intent.confidence,
        )

    @staticmethod
    def _extract_parameters_from_intent(intent) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if intent.gain_target is not None:
            params["gain"] = intent.gain_target
        if intent.vcc is not None:
            params["vcc"] = intent.vcc
        if intent.frequency is not None:
            params["frequency"] = intent.frequency
        return params

    def _generate_questions(self, template_id: str, missing_params: List[str]) -> List[ClarifyingQuestion]:
        questions: List[ClarifyingQuestion] = []

        question_templates = {
            "topology": ClarifyingQuestion(
                field="topology",
                question="What type of amplifier circuit do you want to create?",
                suggestions=[
                    "BJT Common Emitter",
                    "BJT Common Collector",
                    "OpAmp Inverting",
                    "OpAmp Non-Inverting",
                ],
                required=True,
            ),
            "vcc": ClarifyingQuestion(
                field="vcc",
                question="What is the power supply voltage (VCC)?",
                suggestions=["5V", "9V", "12V", "15V"],
                required=True,
            ),
            "gain": ClarifyingQuestion(
                field="gain",
                question="What is the desired voltage gain?",
                suggestions=["10", "20", "50", "100"],
                required=True,
            ),
            "frequency": ClarifyingQuestion(
                field="frequency",
                question="What is the target frequency range?",
                suggestions=["DC-1kHz", "1kHz-100kHz", "100kHz-1MHz"],
                required=False,
            ),
        }

        for param in missing_params:
            q = question_templates.get(param)
            if q is not None:
                questions.append(q)

        if not questions and template_id:
            questions.append(question_templates["gain"])
        return questions
