# .\thesis\electronic-chatbot\apps\api\app\application\circuits\prompt_analyzer.py
"""Prompt Analyzer - Phân tích user prompt và detect thông tin thiếu.

Module này chịu trách nhiệm:
 1. Phân tích user prompt (natural language)
 2. Detect nếu prompt rõ ràng, ambiguous hay invalid
 3. Sinh clarifying questions khi cần thêm info
 4. Suggest parameter values dựa trên prompt

Nguyên tắc:
 - Rule-based first: regex patterns, keyword matching (nhanh)
 - LLM fallback: dùng LLM client nếu rule-based không chắc chắn
 - Progressive disclosure: hỏi users từng câu hỏi, không dồn
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import os

from app.application.ai.llm_client import (
    OpenAICompatibleLLMClient,
    ChatMessage,
    LLMClientError,
)


class PromptClarity(Enum):
    """Clarity level of user prompt."""
    CLEAR = "clear"  # All required parameters present
    AMBIGUOUS = "ambiguous"  # Missing some parameters
    INVALID = "invalid"  # Cannot determine intent


@dataclass
class ClarifyingQuestion:
    """A question to ask the user for clarification."""
    field: str  # Parameter name (e.g., "vcc", "gain", "topology")
    question: str  # User-friendly question
    suggestions: List[str]  # Suggested values or ranges
    required: bool = True  # Is this parameter required?


@dataclass
class PromptAnalysis:
    """Result of analyzing a user prompt."""
    clarity: PromptClarity
    template_id: Optional[str] = None  # Detected template
    parameters: Dict[str, Any] = None  # Extracted parameters
    questions: List[ClarifyingQuestion] = None  # Questions to ask if ambiguous
    confidence: float = 0.0  # Confidence in template detection (0.0-1.0)
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}
        if self.questions is None:
            self.questions = []


class PromptAnalyzer:
    """Analyzes user prompts and detects missing parameters."""

    # Mapping từ NLUService circuit_type → template_id dùng bởi GenerateCircuitUseCase
    CIRCUIT_TYPE_TO_TEMPLATE_ID: Dict[str, str] = {
        "common_emitter":  "bjt_common_emitter",
        "common_collector": "bjt_common_collector",
        "common_base":     "bjt_common_base",
        "common_source":   "mosfet_common_source",
        "common_drain":    "mosfet_common_drain",
        "common_gate":     "mosfet_common_gate",
        "inverting":       "opamp_inverting",
        "non_inverting":   "opamp_non_inverting",
        "differential":    "opamp_differential",
        "instrumentation": "opamp_instrumentation",
        "class_a":         "bjt_class_a",
        "class_ab":        "bjt_class_ab",
        "class_b":         "bjt_class_b",
        "darlington":      "bjt_darlington",
        "multi_stage":     "bjt_multi_stage",
    }

    def _get_llm_env(self) -> Dict[str, Any]:
        """Read optional LLM configuration from environment.

        Intentionally does NOT depend on app.core.config to avoid requiring
        DATABASE_URL / KiCad paths just to import and run prompt analysis.
        """
        llm_enabled = (os.getenv("LLM_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        model = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        timeout_sec = float(os.getenv("LLM_TIMEOUT_SEC") or "20")
        return {
            "enabled": llm_enabled,
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "timeout_sec": timeout_sec,
        }
    
    # Keywords for template detection
    TEMPLATE_KEYWORDS = {
        "bjt_common_emitter": ["bjt", "common emitter", "ce amplifier", "transistor", "npn", "pnp"],
        "bjt_common_collector": ["bjt", "common collector", "cc amplifier", "emitter follower"],
        "bjt_common_base": ["bjt", "common base", "cb amplifier"],
        "opamp_inverting": ["opamp", "op-amp", "inverting", "inverting amplifier"],
        "opamp_non_inverting": ["opamp", "op-amp", "non-inverting", "non inverting"],
        "opamp_differential": ["opamp", "op-amp", "differential", "diff amp"],
    }
    
    # Required parameters for each template
    TEMPLATE_REQUIREMENTS = {
        "bjt_common_emitter": ["vcc", "gain"],
        "bjt_common_collector": ["vcc", "gain"],
        "bjt_common_base": ["vcc", "gain"],
        "opamp_inverting": ["gain"],
        "opamp_non_inverting": ["gain"],
        "opamp_differential": ["gain"],
    }
    
    # Parameter patterns for extraction
    PARAMETER_PATTERNS = {
        "vcc": ["vcc", "supply voltage", "power supply", "v+"],
        "gain": ["gain", "amplification", "av"],
        "frequency": ["frequency", "freq", "hz", "khz", "mhz"],
    }
    
    def analyze(self, prompt: str, parameters: Optional[Dict[str, Any]] = None) -> PromptAnalysis:
        """Analyze user prompt — delegates to NLUService (rule-based + Gemini hybrid).

        Falls back to legacy keyword matching if NLUService is unavailable.

        Args:
            prompt: User's natural language prompt
            parameters: Explicitly provided parameters (override extraction)

        Returns:
            PromptAnalysis with clarity level and questions if needed
        """
        if parameters is None:
            parameters = {}

        # ── Primary path: NLUService ──
        try:
            from app.application.ai.nlu_service import NLUService
            intent = NLUService().understand(prompt)

            template_id = self.CIRCUIT_TYPE_TO_TEMPLATE_ID.get(
                intent.circuit_type, intent.circuit_type or None
            ) if intent.circuit_type and intent.circuit_type != "unknown" else None

            # Build parameters dict from intent
            extracted: Dict[str, Any] = {}
            if intent.gain_target is not None:
                extracted["gain"] = intent.gain_target
            if intent.vcc is not None:
                extracted["vcc"] = intent.vcc
            if intent.frequency is not None:
                extracted["frequency"] = intent.frequency
            all_params = {**extracted, **parameters}

            # Determine clarity
            if not template_id or intent.confidence < 0.3:
                return PromptAnalysis(
                    clarity=PromptClarity.INVALID,
                    confidence=intent.confidence,
                    questions=[
                        ClarifyingQuestion(
                            field="topology",
                            question="What type of amplifier circuit do you want to create?",
                            suggestions=[
                                "BJT Common Emitter", "BJT Common Collector",
                                "OpAmp Inverting", "OpAmp Non-Inverting",
                            ],
                            required=True,
                        )
                    ],
                )

            required_params = self.TEMPLATE_REQUIREMENTS.get(template_id, ["gain"])
            missing_params = [p for p in required_params if p not in all_params or all_params[p] is None]

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

        except Exception:
            # ── Fallback: legacy keyword matching ──
            return self._legacy_analyze(prompt, parameters)

    def _legacy_analyze(self, prompt: str, parameters: Optional[Dict[str, Any]] = None) -> PromptAnalysis:
        """Legacy keyword-based analysis (fallback when NLUService unavailable)."""
        if parameters is None:
            parameters = {}

        prompt_lower = prompt.lower()

        llm_env = self._get_llm_env()
        if llm_env["enabled"] and llm_env.get("api_key"):
            try:
                llm_analysis = self._analyze_with_llm(prompt=prompt, parameters=parameters, llm_env=llm_env)
                if llm_analysis is not None:
                    return llm_analysis
            except Exception:
                pass
        
        # Detect template from prompt
        template_id, confidence = self._detect_template(prompt_lower)
        
        # Lowered threshold: accept if at least one keyword matches (confidence >= 0.15)
        if not template_id or confidence < 0.15:
            return PromptAnalysis(
                clarity=PromptClarity.INVALID,
                confidence=confidence,
                questions=[
                    ClarifyingQuestion(
                        field="topology",
                        question="What type of amplifier circuit do you want to create?",
                        suggestions=[
                            "BJT Common Emitter",
                            "BJT Common Collector",
                            "OpAmp Inverting",
                            "OpAmp Non-Inverting"
                        ],
                        required=True
                    )
                ]
            )
        
        # Extract parameters from prompt
        extracted_params = self._extract_parameters(prompt_lower)
        
        # Merge with explicitly provided parameters (explicit takes priority)
        all_params = {**extracted_params, **parameters}
        
        # Check if all required parameters are present
        required_params = self.TEMPLATE_REQUIREMENTS.get(template_id, [])
        missing_params = [p for p in required_params if p not in all_params or all_params[p] is None]
        
        if not missing_params:
            # All required parameters present
            return PromptAnalysis(
                clarity=PromptClarity.CLEAR,
                template_id=template_id,
                parameters=all_params,
                confidence=confidence
            )
        else:
            # Generate clarifying questions for missing parameters
            questions = self._generate_questions(template_id, missing_params)
            
            return PromptAnalysis(
                clarity=PromptClarity.AMBIGUOUS,
                template_id=template_id,
                parameters=all_params,
                questions=questions,
                confidence=confidence
            )
    
    def _detect_template(self, prompt: str) -> tuple[Optional[str], float]:
        """Detect template ID from prompt using keyword matching.
        
        Args:
            prompt: Normalized (lowercase) prompt
        
        Returns:
            Tuple of (template_id, confidence)
        """
        best_match = None
        best_score = 0.0
        
        for template_id, keywords in self.TEMPLATE_KEYWORDS.items():
            score = 0.0
            for keyword in keywords:
                if keyword in prompt:
                    score += 1.0
            
            # Normalize score by number of keywords
            score = score / len(keywords)
            
            if score > best_score:
                best_score = score
                best_match = template_id
        
        return best_match, best_score
    
    def _extract_parameters(self, prompt: str) -> Dict[str, Any]:
        """Extract parameter values from prompt.
        
        Args:
            prompt: Normalized (lowercase) prompt
        
        Returns:
            Dict of extracted parameters
        """
        params = {}
        
        # Extract VCC (e.g., "12V", "12v", "vcc=12")
        import re
        
        # VCC patterns
        vcc_patterns = [
            r"vcc[:\s=]+(\d+\.?\d*)\s*v",
            r"supply[:\s=]+(\d+\.?\d*)\s*v",
            r"(\d+\.?\d*)\s*v\s+supply",
            r"v\+[:\s=]+(\d+\.?\d*)",
        ]
        for pattern in vcc_patterns:
            match = re.search(pattern, prompt)
            if match:
                params["vcc"] = float(match.group(1))
                break
        
        # Gain patterns
        gain_patterns = [
            r"gain[:\s=]+(\d+\.?\d*)",
            r"amplification[:\s=]+(\d+\.?\d*)",
            r"av[:\s=]+(\d+\.?\d*)",
            r"gain\s+of\s+(\d+\.?\d*)",
        ]
        for pattern in gain_patterns:
            match = re.search(pattern, prompt)
            if match:
                params["gain"] = float(match.group(1))
                break
        
        return params
    
    def _generate_questions(
        self,
        template_id: str,
        missing_params: List[str]
    ) -> List[ClarifyingQuestion]:
        """Generate clarifying questions for missing parameters.
        
        Args:
            template_id: Detected template ID
            missing_params: List of missing parameter names
        
        Returns:
            List of ClarifyingQuestion objects
        """
        questions = []
        
        # Question templates for common parameters
        question_templates = {
            "vcc": ClarifyingQuestion(
                field="vcc",
                question="What is the power supply voltage (VCC)?",
                suggestions=["5V", "9V", "12V", "15V"],
                required=True
            ),
            "gain": ClarifyingQuestion(
                field="gain",
                question="What is the desired voltage gain?",
                suggestions=["10", "20", "50", "100"],
                required=True
            ),
            "frequency": ClarifyingQuestion(
                field="frequency",
                question="What is the target frequency range?",
                suggestions=["DC-1kHz (audio)", "1kHz-100kHz (general)", "100kHz-1MHz (RF)"],
                required=False
            ),
        }
        
        for param in missing_params:
            if param in question_templates:
                questions.append(question_templates[param])
        
        return questions

    def _analyze_with_llm(self, prompt: str, parameters: Dict[str, Any], llm_env: Dict[str, Any]) -> Optional[PromptAnalysis]:
        """Use an LLM to extract structured intent.

        Returns None if LLM output is unusable, so caller can fallback.
        """
        api_key = llm_env.get("api_key")
        if not api_key:
            return None

        template_ids = self._get_available_template_ids()

        system = (
            "You are an intent extraction engine for an electronics circuit generator. "
            "Given a user prompt, output ONLY a single JSON object with this schema:\n"
            "{\n"
            "  \"clarity\": \"clear\"|\"ambiguous\"|\"invalid\",\n"
            "  \"template_id\": string|null,\n"
            "  \"parameters\": object,\n"
            "  \"missing_fields\": string[],\n"
            "  \"questions\": [{\"field\":string,\"question\":string,\"suggestions\":string[],\"required\":boolean}],\n"
            "  \"confidence\": number\n"
            "}\n"
            "Rules:\n"
            "- template_id MUST be one of the provided available_template_ids, or null.\n"
            "- parameters should be numeric where possible.\n"
            "- If intent is unclear, set clarity=invalid and ask for topology.\n"
            "- If some required parameters are missing, set clarity=ambiguous and provide questions.\n"
            "- Never include markdown or extra keys."
        )

        user = {
            "prompt": prompt,
            "explicit_parameters": parameters or {},
            "available_template_ids": template_ids,
            "required_params_by_template": self.TEMPLATE_REQUIREMENTS,
        }

        client = OpenAICompatibleLLMClient(
            api_key=api_key,
            base_url=str(llm_env.get("base_url") or "https://api.openai.com/v1"),
            model=str(llm_env.get("model") or "gpt-4o-mini"),
            timeout_sec=float(llm_env.get("timeout_sec") or 20.0),
        )

        try:
            obj = client.chat_json(
                messages=[
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=__import__("json").dumps(user, ensure_ascii=False)),
                ],
                temperature=0.0,
                max_tokens=700,
            )
        except LLMClientError:
            return None

        clarity = str(obj.get("clarity") or "").strip().lower()
        template_id = obj.get("template_id")
        confidence = float(obj.get("confidence") or 0.0)

        if clarity not in {"clear", "ambiguous", "invalid"}:
            return None

        if template_id is not None:
            if not isinstance(template_id, str):
                return None
            if template_id not in template_ids:
                # Force invalid if model picked unsupported template
                template_id = None
                clarity = "invalid"

        llm_params = obj.get("parameters") if isinstance(obj.get("parameters"), dict) else {}
        # Explicit parameters always win
        all_params = {**llm_params, **(parameters or {})}

        questions: List[ClarifyingQuestion] = []
        raw_questions = obj.get("questions")
        if isinstance(raw_questions, list):
            for q in raw_questions:
                if not isinstance(q, dict):
                    continue
                field = q.get("field")
                question = q.get("question")
                suggestions = q.get("suggestions")
                required = q.get("required", True)
                if isinstance(field, str) and isinstance(question, str) and isinstance(suggestions, list):
                    suggestions_str = [str(s) for s in suggestions][:10]
                    questions.append(
                        ClarifyingQuestion(
                            field=field,
                            question=question,
                            suggestions=suggestions_str,
                            required=bool(required),
                        )
                    )

        if clarity == "clear" and template_id:
            return PromptAnalysis(
                clarity=PromptClarity.CLEAR,
                template_id=template_id,
                parameters=all_params,
                questions=[],
                confidence=confidence,
            )

        if clarity == "ambiguous" and template_id:
            if not questions:
                # Ensure at least one question exists
                questions = self._generate_questions(template_id, self.TEMPLATE_REQUIREMENTS.get(template_id, []))
            return PromptAnalysis(
                clarity=PromptClarity.AMBIGUOUS,
                template_id=template_id,
                parameters=all_params,
                questions=questions,
                confidence=confidence,
            )

        # invalid
        if not questions:
            questions = [
                ClarifyingQuestion(
                    field="topology",
                    question="What type of circuit do you want to create?",
                    suggestions=template_ids[:8],
                    required=True,
                )
            ]
        return PromptAnalysis(
            clarity=PromptClarity.INVALID,
            template_id=None,
            parameters=all_params,
            questions=questions,
            confidence=confidence,
        )

    def _get_available_template_ids(self) -> List[str]:
        """Return available template ids from registries.

        Uses runtime imports to avoid circular dependencies during module import.
        """
        template_ids: List[str] = []
        try:
            from app.domains.circuits.templates_loader import get_loader

            template_ids.extend(get_loader().get_all_types())
        except Exception:
            pass

        # Also include keyword-based templates as fallback set
        template_ids.extend(list(self.TEMPLATE_KEYWORDS.keys()))

        # Deduplicate while preserving order
        seen = set()
        result: List[str] = []
        for t in template_ids:
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return result
