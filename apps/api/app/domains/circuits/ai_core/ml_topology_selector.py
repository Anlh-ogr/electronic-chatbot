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


class XGBoostTopologySelector:
    """ML advisor dùng XGBoost để score topology/block từ UserSpec."""

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
        schema_path = self._model_dir / "xgb_feature_schema.json"
        topology_model_path = self._model_dir / "xgb_topology_model.json"
        block_model_path = self._model_dir / "xgb_block_model.json"

        if not schema_path.exists() or not topology_model_path.exists() or not block_model_path.exists():
            logger.info("ML topology models not found at %s; fallback to rule-based", self._model_dir)
            return

        try:
            import json
            import xgboost as xgb

            with open(schema_path, "r", encoding="utf-8") as f:
                schema = json.load(f)

            self._feature_names = [str(name) for name in schema.get("feature_names", [])]
            self._extra_requirement_keys = [str(name) for name in schema.get("extra_requirement_keys", [])]
            self._topology_classes = [str(name) for name in schema.get("topology_classes", [])]
            self._block_classes = [str(name) for name in schema.get("block_classes", [])]

            if not self._feature_names or not self._topology_classes or not self._block_classes:
                logger.warning("ML schema is incomplete; fallback to rule-based")
                return

            self._xgb = xgb
            self._topology_model = xgb.XGBClassifier()
            self._block_model = xgb.XGBClassifier()
            self._topology_model.load_model(str(topology_model_path))
            self._block_model.load_model(str(block_model_path))

            self._enabled = True
            logger.info("Loaded XGBoost topology/block models from %s", self._model_dir)
        except Exception as exc:
            logger.warning("Cannot load XGBoost models, fallback to rule-based: %s", exc)
            self._enabled = False
