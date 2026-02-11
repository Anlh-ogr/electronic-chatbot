
"""
ParametricEngine - Bộ máy sinh mạch tham số hóa tổng quát (dùng template JSON)

Thay thế các builder riêng lẻ bằng một engine duy nhất dựa trên template JSON.
Tách ra từ template_builder.py để chuẩn hóa kiến trúc domain.
"""

from typing import Dict, Any, Optional, List, TYPE_CHECKING
import copy

if TYPE_CHECKING:
    from app.domains.circuits.templates_loader import TemplatesLoader
    from app.domains.circuits.entities import Circuit

""" Lý do sử dụng thư viện:
typing: Định nghĩa type hint cho Dict, Any, Optional, List giúp code rõ ràng, dễ kiểm tra.
copy: Dùng deepcopy để không làm thay đổi template gốc khi override.
TYPE_CHECKING: Tránh import vòng lặp khi type hint.
app.domains.circuits.templates_loader: Loader lấy template JSON và build Circuit.
app.domains.circuits.entities: Định nghĩa entity Circuit (chỉ dùng type hint).
"""


# ============================================================================
# GENERIC PARAMETRIC ENGINE (Phase 6)
# ============================================================================

class ParametricEngine:
    """
    Bộ máy sinh mạch tổng quát: template JSON + override của user → Circuit entity.

    Thay thế các builder riêng lẻ (MOSFET CS/CD, OpAmp non-inv/diff/inst, ...)
    bằng một engine duy nhất dựa trên hơn 70 template JSON.

    Quy trình:
        1. Load template dict (từ TemplatesLoader)
        2. Kiểm tra override hợp lệ với whitelist parametric
        3. Deep-copy & áp dụng override vào components
        4. Kiểm tra constraint
        5. Build Circuit entity qua TemplatesLoader._build_circuit_from_dict()

    Ví dụ:
        engine = ParametricEngine()
        circuit = engine.build(
            "bjt_ce_voltage_amplifier",
            overrides={"RC": {"resistance": 10000}, "Q1": {"model": "2N3904"}}
        )
    """
    
    def __init__(self, loader: Optional["TemplatesLoader"] = None):
        from app.domains.circuits.templates_loader import TemplatesLoader, get_loader
        self._loader = loader or get_loader()
    
    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    
    def build(
        self,
        template_id: str,
        overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        *,
        validate_constraints: bool = True,
    ) -> "Circuit":
        """
        Sinh Circuit từ template JSON + override của user.

        Args:
            template_id: ID template (vd: "bjt_ce_voltage_amplifier")
            overrides: {component_id: {param_name: value}} override giá trị
            validate_constraints: Kiểm tra constraint sau khi override

        Returns:
            Circuit entity đã áp dụng override

        Raises:
            ValueError: template không tồn tại hoặc override sai whitelist
        """
        tpl = self._loader.get(template_id) or self._loader.get_by_id(template_id)
        if tpl is None:
            raise ValueError(f"Template '{template_id}' does not exist")
        
        tpl = copy.deepcopy(tpl)
        
        if overrides:
            self._validate_overrides(tpl, overrides)
            self._apply_overrides(tpl, overrides)
        
        if validate_constraints:
            warnings = self._check_constraints(tpl)
            # warnings are logged only, don't raise
            # (errors already raised in _check_constraints if hard constraint violated)
        
        from app.domains.circuits.templates_loader import TemplatesLoader
        return TemplatesLoader._build_circuit_from_dict(tpl)
    
    def list_tunable_params(self, template_id: str) -> Dict[str, Dict[str, str]]:
        """
        Trả về whitelist các tham số có thể chỉnh (cho UI/LLM).

        Returns:
            {component_id: {param_name: "optional", "note": "..."}}
        """
        tpl = self._loader.get(template_id) or self._loader.get_by_id(template_id)
        if tpl is None:
            return {}
        return dict(tpl.get("parametric", {}))
    
    def get_defaults(self, template_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Trả về giá trị mặc định hiện tại cho từng tham số có thể chỉnh.

        Returns:
            {component_id: {param_name: default_value}}
        """
        tpl = self._loader.get(template_id) or self._loader.get_by_id(template_id)
        if tpl is None:
            return {}
        
        parametric = tpl.get("parametric", {})
        defaults: Dict[str, Dict[str, Any]] = {}
        
        comp_map = {c["id"]: c for c in tpl.get("components", [])}
        for comp_id, param_spec in parametric.items():
            comp_data = comp_map.get(comp_id)
            if comp_data is None:
                continue
            params = comp_data.get("parameters", {})
            entry: Dict[str, Any] = {}
            for pname in param_spec:
                if pname == "note":
                    continue
                if pname in params:
                    entry[pname] = params[pname]
            if entry:
                defaults[comp_id] = entry
        
        return defaults
    
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    
    @staticmethod
    def _validate_overrides(
        tpl: Dict[str, Any],
        overrides: Dict[str, Dict[str, Any]],
    ) -> None:
        """
        Kiểm tra override chỉ chứa key hợp lệ trong whitelist parametric.
        """
        parametric = tpl.get("parametric", {})
        comp_ids = {c["id"] for c in tpl.get("components", [])}
        
        for comp_id, param_dict in overrides.items():
            if comp_id not in comp_ids:
                raise ValueError(
                    f"Override component '{comp_id}' does not exist in template"
                )
            if comp_id not in parametric:
                raise ValueError(
                    f"Component '{comp_id}' not in parametric whitelist"
                )
            allowed = parametric[comp_id]
            for pname in param_dict:
                if pname not in allowed:
                    raise ValueError(
                        f"Parameter '{pname}' of '{comp_id}' not in "
                        f"parametric whitelist (allowed: {list(allowed.keys())})"
                    )
    
    @staticmethod
    def _apply_overrides(
        tpl: Dict[str, Any],
        overrides: Dict[str, Dict[str, Any]],
    ) -> None:
        """
        Ghi đè giá trị vào components[].parameters.
        """
        for comp in tpl.get("components", []):
            comp_id = comp.get("id")
            if comp_id in overrides:
                params = comp.setdefault("parameters", {})
                for pname, pval in overrides[comp_id].items():
                    params[pname] = pval
    
    @staticmethod
    def _check_constraints(tpl: Dict[str, Any]) -> List[str]:
        """
        Kiểm tra constraint sau khi override. Trả về list cảnh báo.
        Raise ValueError nếu vi phạm constraint cứng.
        """
        warnings: List[str] = []
        constraints = tpl.get("constraints", [])
        comp_map = {c["id"]: c for c in tpl.get("components", [])}
        
        for con in constraints:
            ctype = con.get("type", "")
            target = con.get("target")
            comp = comp_map.get(target, {}) if target else {}
            params = comp.get("parameters", {})
            
            if ctype == "voltage_range":
                v = params.get("voltage")
                cmin = con.get("min")
                cmax = con.get("max")
                if v is not None:
                    if cmin is not None and v < cmin:
                        raise ValueError(
                            f"Constraint violated: {target} voltage={v} < min={cmin}"
                        )
                    if cmax is not None and v > cmax:
                        raise ValueError(
                            f"Constraint violated: {target} voltage={v} > max={cmax}"
                        )
            
            elif ctype == "current_limit":
                cmax = con.get("max")
                i_val = params.get("current")
                if cmax is not None and i_val is not None and i_val > cmax:
                    raise ValueError(
                        f"Constraint violated: {target} current={i_val} > max={cmax}"
                    )
            
            elif ctype == "power_rating_min":
                min_w = con.get("min_watts")
                pr = params.get("power_rating")
                if min_w is not None and pr is not None and pr < min_w:
                    warnings.append(
                        f"Component {target}: power_rating {pr}W < recommended {min_w}W"
                    )
            
            elif ctype == "voltage_rating_min":
                min_vr = con.get("min")
                vr = params.get("voltage_rating")
                if min_vr is not None and vr is not None and vr < min_vr:
                    warnings.append(
                        f"Component {target}: voltage_rating {vr}V < recommended {min_vr}V"
                    )
        
        return warnings
