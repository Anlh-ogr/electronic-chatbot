from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .spec_parser import UserSpec

logger = logging.getLogger(__name__)

_API_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_DEFAULT_MODEL_DIR = _API_ROOT / "resources" / "ml_models"


def _normalize_token(value: str) -> str:
    token = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return token.strip("_")


class RandomForestTopologySelector:
    """ML advisor dùng Random Forest để score topology/block từ UserSpec.
    Nếu yêu cầu thiết kế không cụ thể (VD: thiếu thông số quan trọng), mô hình sẽ dựa vào
    phân phối chung của dữ liệu huấn luyện, và trả về xác suất dàn đều hơn. Lúc này hệ thống tự động
    fallback về rule-based hoặc đưa ra cấu hình mặc định (default templates).
    """

    INPUT_MODES = ("single_ended", "differential")
    SUPPLY_MODES = ("auto", "single_supply", "dual_supply")
    DEVICE_PREFS = ("auto", "bjt", "mosfet", "opamp")
    COUPLING_PREFS = ("auto", "capacitor", "direct", "transformer")

    def __init__(self, model_dir: Optional[Path] = None) -> None:
        self._model_dir = model_dir or _DEFAULT_MODEL_DIR
        self._enabled = False

        self._xgb = None
        self._topology_model = None
        self._block_model = None

        self._feature_names: List[str] = []
        self._extra_requirement_keys: List[str] = []
        self._topology_classes: List[str] = []
        self._block_classes: List[str] = []

        self._load()

    @property
    def is_available(self) -> bool:
        return self._enabled

    @classmethod
    def build_feature_names(
        cls,
        extra_requirement_keys: Optional[Sequence[str]] = None,
    ) -> List[str]:
        names: List[str] = [
            "gain",
            "log_gain",
            "vcc",
            "frequency_log",
            "input_channels",
            "high_cmr",
            "output_buffer",
            "power_output",
            "is_differential_input",
        ]

        names.extend([f"input_mode__{mode}" for mode in cls.INPUT_MODES])
        names.extend([f"supply_mode__{mode}" for mode in cls.SUPPLY_MODES])
        names.extend([f"device_preference__{pref}" for pref in cls.DEVICE_PREFS])
        names.extend([f"coupling_preference__{pref}" for pref in cls.COUPLING_PREFS])

        if extra_requirement_keys:
            for key in sorted(set(extra_requirement_keys)):
                names.append(f"extra_req__{_normalize_token(key)}")
        return names

    @classmethod
    def build_feature_map(
        cls,
        *,
        gain: Optional[float],
        vcc: Optional[float],
        frequency: Optional[float],
        input_channels: int,
        high_cmr: bool,
        input_mode: str,
        output_buffer: bool,
        power_output: bool,
        supply_mode: str,
        coupling_preference: str,
        device_preference: str,
        extra_requirements: Sequence[str],
        extra_requirement_keys: Optional[Sequence[str]] = None,
    ) -> Dict[str, float]:
        safe_gain = float(gain) if gain is not None else 1.0
        safe_vcc = float(vcc) if vcc is not None else 12.0
        safe_frequency = float(frequency) if frequency is not None else 1_000.0

        fmap: Dict[str, float] = {
            "gain": safe_gain,
            "log_gain": math.log10(max(1e-6, abs(safe_gain))),
            "vcc": safe_vcc,
            "frequency_log": math.log10(max(1.0, safe_frequency)),
            "input_channels": float(max(1, input_channels)),
            "high_cmr": 1.0 if high_cmr else 0.0,
            "output_buffer": 1.0 if output_buffer else 0.0,
            "power_output": 1.0 if power_output else 0.0,
            "is_differential_input": 1.0 if input_mode == "differential" else 0.0,
        }

        for mode in cls.INPUT_MODES:
            fmap[f"input_mode__{mode}"] = 1.0 if input_mode == mode else 0.0
        for mode in cls.SUPPLY_MODES:
            fmap[f"supply_mode__{mode}"] = 1.0 if supply_mode == mode else 0.0
        for pref in cls.DEVICE_PREFS:
            fmap[f"device_preference__{pref}"] = 1.0 if device_preference == pref else 0.0
        for pref in cls.COUPLING_PREFS:
            fmap[f"coupling_preference__{pref}"] = 1.0 if coupling_preference == pref else 0.0

        req_tokens = {_normalize_token(req) for req in extra_requirements}
        for key in (extra_requirement_keys or []):
            token = _normalize_token(key)
            fmap[f"extra_req__{token}"] = 1.0 if token in req_tokens else 0.0

        return fmap

    def _spec_to_vector(self, spec: UserSpec) -> List[float]:
        fmap = self.build_feature_map(
            gain=spec.gain,
            vcc=spec.vcc,
            frequency=spec.frequency,
            input_channels=spec.input_channels,
            high_cmr=spec.high_cmr,
            input_mode=spec.input_mode,
            output_buffer=spec.output_buffer,
            power_output=spec.power_output,
            supply_mode=spec.supply_mode,
            coupling_preference=spec.coupling_preference,
            device_preference=spec.device_preference,
            extra_requirements=spec.extra_requirements,
            extra_requirement_keys=self._extra_requirement_keys,
        )
        return [float(fmap.get(name, 0.0)) for name in self._feature_names]

    def _get_heuristic_reason(self, topology: str, spec: UserSpec) -> str:
        """Attach lightweight explanations based on the UserSpec and predicted topology."""
        reasons = []
        
        # Approximate mapping from UserSpec parameters to prompt examples
        # UserSpec uses e.g., gain, frequency, input_mode, output_buffer, power_output
        gain = spec.gain if spec.gain is not None else 1.0
        frequency = spec.frequency if spec.frequency is not None else 1000.0
        
        if gain > 100 and "multi_stage" in topology:
            reasons.append("High gain requirement suggests a multi-stage design.")
        if spec.high_cmr and "opamp" in topology:
            reasons.append("Op-amp suitable for high CMRR/low noise handling.")
        if frequency > 10e6 and "cg" in topology:
            reasons.append("Common-gate configuration provides excellent high-frequency response.")
        if "cc" in topology or "cd" in topology:
            reasons.append("Good choice for a voltage buffer with impedance matching.")
        if spec.power_output and "class" in topology:
            reasons.append("Power amplifier topology chosen to drive heavy load or speaker.")
            
        if not reasons:
            reasons.append("Well-balanced configuration for general specifications.")
            
        return " ".join(reasons)

    def _check_uncertainty(self, probs: Sequence[float], top_k_indices: Sequence[int]) -> bool:
        """Check if the prediction is highly uncertain based on probabilities."""
        if len(top_k_indices) < 2:
            return False
            
        top_prob = probs[top_k_indices[0]]
        second_prob = probs[top_k_indices[1]]
        
        # Uncertainty conditions: Low maximum confidence OR very close top candidates
        if top_prob < 0.25 or (top_prob - second_prob) < 0.05:
            return True
            
        return False

    def predict_topologies(
        self, 
        spec: UserSpec, 
        top_k: int = 3, 
        threshold: float = 0.15
    ) -> Dict[str, Any]:
        """Recommend and rank top-k possible circuit topologies based on UserSpec."""
        if not self._enabled:
            return {
                "status": "unavailable",
                "candidates": [],
                "suggestion": "ML model disabled or not found; falling back to rule-based engine."
            }

        x = [self._spec_to_vector(spec)]

        try:
            topology_proba = self._topology_model.predict_proba(x)[0]
        except Exception as exc:
            logger.warning("ML predict_topologies failed: %s", exc)
            return {
                "status": "error",
                "candidates": [],
                "suggestion": "Error during prediction; fallback to rule-based engine."
            }
            
        # Get descending sort of indices
        # Ensure we don't request more than available classes
        actual_top_k = min(top_k, len(self._topology_classes))
        
        # Sort indices descending by probability
        indices = sorted(range(len(topology_proba)), key=lambda i: topology_proba[i], reverse=True)
        
        results = []
        is_uncertain = self._check_uncertainty(topology_proba, indices[:actual_top_k])
        
        for i in indices[:actual_top_k]:
            score = float(topology_proba[i])
            
            # Filter low-probability candidates reducing design space
            if score < threshold:
                continue
                
            topology_name = self._topology_classes[i]
            reason = self._get_heuristic_reason(topology_name, spec)
            
            results.append({
                "topology": topology_name,
                "score": round(score, 4),
                "reason": reason
            })
            
        return {
            "status": "uncertain" if is_uncertain else "confident",
            "candidates": results,
            "suggestion": "Ask user for more specific preference or fallback to rule-based engine." if is_uncertain else "Proceed with top candidate."
        }

    def predict_context(self, spec: UserSpec) -> Optional[Dict[str, Dict[str, float]]]:
        if not self._enabled:
            return None

        x = [self._spec_to_vector(spec)]

        try:
            topology_proba = self._topology_model.predict_proba(x)[0]
            block_proba = self._block_model.predict_proba(x)[0]
        except Exception as exc:
            logger.warning("ML predict failed: %s", exc)
            return None

        topology_map = {
            self._topology_classes[idx]: float(prob)
            for idx, prob in enumerate(topology_proba)
        }
        block_map = {
            self._block_classes[idx]: float(prob)
            for idx, prob in enumerate(block_proba)
        }
        return {"topology": topology_map, "block": block_map}

    def score_candidate(
        self,
        meta: Dict[str, Any],
        context: Optional[Dict[str, Dict[str, float]]],
    ) -> float:
        if not context:
            return 0.5

        family = meta.get("domain", {}).get("family", "")
        family_prob = context.get("topology", {}).get(family, 0.0)

        blocks = meta.get("functional_structure", {}).get("blocks", [])
        block_types = [
            str(block.get("type", ""))
            for block in blocks
            if isinstance(block, dict)
        ]

        if not block_types:
            return max(0.0, min(family_prob, 1.0))

        block_probs = [context.get("block", {}).get(block_type, 0.0) for block_type in block_types]
        max_block_prob = max(block_probs) if block_probs else 0.0

        score = 0.7 * family_prob + 0.3 * max_block_prob
        return max(0.0, min(score, 1.0))

    def _load(self) -> None:
        schema_path = self._model_dir / "rf_feature_schema.json"
        topology_model_path = self._model_dir / "rf_topology_model.joblib"
        block_model_path = self._model_dir / "rf_block_model.joblib"

        if not schema_path.exists() or not topology_model_path.exists() or not block_model_path.exists():
            logger.info("ML topology models not found at %s; fallback to rule-based", self._model_dir)
            return

        try:
            import json
            import joblib

            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            self._feature_names = [str(name) for name in schema.get("feature_names", [])]
            self._extra_requirement_keys = [str(name) for name in schema.get("extra_requirement_keys", [])]
            self._topology_classes = [str(name) for name in schema.get("topology_classes", [])]
            self._block_classes = [str(name) for name in schema.get("block_classes", [])]

            if not self._feature_names or not self._topology_classes or not self._block_classes:
                logger.warning("ML schema is incomplete; fallback to rule-based")
                return

            self._topology_model = joblib.load(topology_model_path)
            self._block_model = joblib.load(block_model_path)

            self._enabled = True
            logger.info("Loaded Random Forest topology/block models from %s", self._model_dir)
        except Exception as exc:
            logger.warning("Cannot load Random Forest models, fallback to rule-based: %s", exc)
            self._enabled = False
