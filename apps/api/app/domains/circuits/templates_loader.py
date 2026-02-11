# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\templates_loader.py
"""
Template Loader - Tải và quản lý toàn bộ JSON circuit templates.

Module chịu trách nhiệm:
 1. Đọc tất cả file JSON trong resources/templates/ (trừ _index*.json)
 2. Chuẩn hóa component type qua ComponentType.normalize()
 3. Cung cấp registry tra cứu theo topology_type, category, template_id
 4. Cung cấp helper build Circuit entity từ JSON template

Nguyên tắc:
 - Là infrastructure adapter, KHÔNG chứa business logic.
 - Chỉ phụ thuộc entities.py (ComponentType, Component, Net, …).
 - Thread-safe: dữ liệu nội bộ là immutable sau khi load.
 - Tương thích với hệ thống SchTopologyTemplateRegistry hiện tại.

Sử dụng:
    from app.domains.circuits.templates_loader import TemplatesLoader

    loader = TemplatesLoader()           # tự động load lần đầu
    tpl = loader.get("bjt_ce_voltage_amplifier")
    tpls = loader.by_category("opamp")
    circuit = loader.build_circuit("bjt_ce_voltage_amplifier", parameters={...})
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .entities import (
    Circuit,
    Component,
    ComponentType,
    Constraint,
    Net,
    ParameterValue,
    PinRef,
    Port,
    PortDirection,
)

logger = logging.getLogger(__name__)

# Đường dẫn mặc định tới thư mục chứa JSON templates
# __file__ → circuits/ → domains/ → app/ → api(root) → resources/templates
_DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "resources" / "templates"


class TemplatesLoader:
    """
    Registry trung tâm – load & tra cứu toàn bộ JSON circuit templates.

    Attributes
    ----------
    _templates : dict[str, dict]
        Mapping topology_type → raw JSON dict (đã chuẩn hóa type).
    _by_category : dict[str, list[str]]
        Mapping category → list topology_type.
    _by_id : dict[str, str]
        Mapping template_id (e.g. "OP-01") → topology_type.
    """

    def __init__(self, templates_dir: str | Path | None = None, *, auto_load: bool = True):
        self._templates: Dict[str, Dict[str, Any]] = {}
        self._by_category: Dict[str, List[str]] = {}
        self._by_id: Dict[str, str] = {}
        self._dir = Path(templates_dir) if templates_dir else _DEFAULT_TEMPLATES_DIR

        if auto_load:
            self.load_all()

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_all(self) -> int:
        """Đọc toàn bộ *.json trong templates_dir (trừ _index*).

        Returns
        -------
        int
            Số lượng template đã load thành công.
        """
        self._templates.clear()
        self._by_category.clear()
        self._by_id.clear()

        if not self._dir.is_dir():
            logger.warning("Templates directory không tồn tại: %s", self._dir)
            return 0

        count = 0
        for fpath in sorted(self._dir.glob("*.json")):
            if fpath.name.startswith("_index"):
                continue
            try:
                tpl = self._read_and_normalize(fpath)
                topo = tpl["topology_type"]
                self._templates[topo] = tpl

                # Index by category
                cat = tpl.get("category", "unknown")
                self._by_category.setdefault(cat, []).append(topo)

                # Index by template_id (nếu có)
                tid = tpl.get("template_id")
                if tid:
                    self._by_id[tid] = topo

                count += 1
            except Exception:
                logger.exception("Không thể load template: %s", fpath.name)

        logger.info("Đã load %d / %d JSON templates từ %s", count, count, self._dir)
        return count

    # ------------------------------------------------------------------
    # Tra cứu
    # ------------------------------------------------------------------
    def get(self, topology_type: str) -> Optional[Dict[str, Any]]:
        """Lấy template dict theo topology_type. Trả về None nếu không tìm thấy."""
        return self._templates.get(topology_type)

    def get_or_raise(self, topology_type: str) -> Dict[str, Any]:
        """Lấy template hoặc raise ValueError."""
        tpl = self._templates.get(topology_type)
        if tpl is None:
            raise ValueError(
                f"Topology '{topology_type}' không tồn tại. "
                f"Có {len(self._templates)} templates. "
                f"Dùng get_all_types() để xem danh sách."
            )
        return tpl

    def get_by_id(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Tra cứu template qua template_id (e.g. 'OP-01', 'DAR-04')."""
        topo = self._by_id.get(template_id)
        return self._templates.get(topo) if topo else None

    def by_category(self, category: str) -> List[Dict[str, Any]]:
        """Trả về list templates thuộc category."""
        topos = self._by_category.get(category, [])
        return [self._templates[t] for t in topos]

    def get_all_types(self) -> List[str]:
        """Danh sách toàn bộ topology_type."""
        return sorted(self._templates.keys())

    def get_categories(self) -> List[str]:
        """Danh sách toàn bộ categories."""
        return sorted(self._by_category.keys())

    def has(self, topology_type: str) -> bool:
        return topology_type in self._templates

    def count(self) -> int:
        return len(self._templates)

    def summary(self) -> Dict[str, int]:
        """Trả về dict category → count."""
        return {cat: len(topos) for cat, topos in sorted(self._by_category.items())}

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search(self, query: str) -> List[Dict[str, Any]]:
        """Tìm kiếm templates theo từ khóa (khớp topology_type, description, tags)."""
        q = query.lower()
        results = []
        for tpl in self._templates.values():
            searchable = " ".join([
                tpl.get("topology_type", ""),
                tpl.get("description", ""),
                " ".join(tpl.get("tags", [])),
            ]).lower()
            if q in searchable:
                results.append(tpl)
        return results

    def find_by_components(self, required_types: Set[str]) -> List[Dict[str, Any]]:
        """Tìm templates chứa đúng tập component types yêu cầu."""
        normalized = {ComponentType.normalize(t).value for t in required_types}
        results = []
        for tpl in self._templates.values():
            tpl_types = {c.get("_normalized_type", c.get("type", "")).lower() for c in tpl.get("components", [])}
            if normalized.issubset(tpl_types):
                results.append(tpl)
        return results

    # ------------------------------------------------------------------
    # Build Circuit Entity
    # ------------------------------------------------------------------
    def build_circuit(
        self,
        topology_type: str,
        *,
        parameters: Optional[Dict[str, Dict[str, Any]]] = None,
        custom_name: Optional[str] = None,
    ) -> Circuit:
        """Chuyển đổi JSON template → Circuit entity.

        Parameters
        ----------
        topology_type : str
            Key tra cứu template.
        parameters : dict, optional
            Override tham số linh kiện. VD: {"R1": {"resistance": 10000}}
        custom_name : str, optional
            Tên mạch tùy chỉnh (mặc định lấy từ description).

        Returns
        -------
        Circuit
            Immutable Circuit entity sẵn sàng validate / serialize.
        """
        tpl = self.get_or_raise(topology_type)
        return self._build_circuit_from_dict(tpl, parameters=parameters, custom_name=custom_name)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _read_and_normalize(fpath: Path) -> Dict[str, Any]:
        """Đọc JSON và chuẩn hóa component type strings."""
        with open(fpath, "r", encoding="utf-8") as f:
            tpl = json.load(f)

        # Chuẩn hóa type cho mỗi component
        for comp in tpl.get("components", []):
            raw_type = comp.get("type", "")
            try:
                ct = ComponentType.normalize(raw_type)
                comp["_normalized_type"] = ct.value   # lưu giá trị enum chuẩn
            except ValueError:
                comp["_normalized_type"] = raw_type.lower()
                logger.warning(
                    "Template %s: component '%s' có type không chuẩn: '%s'",
                    fpath.name, comp.get("id"), raw_type,
                )

        # Chuẩn hóa connections sang list-of-list (phòng trường hợp dict format)
        for net in tpl.get("nets", []):
            normalized_conns = []
            for conn in net.get("connections", []):
                if isinstance(conn, dict) and "component" in conn and "pin" in conn:
                    normalized_conns.append([conn["component"], conn["pin"]])
                elif isinstance(conn, (list, tuple)) and len(conn) == 2:
                    normalized_conns.append(list(conn))
                else:
                    normalized_conns.append(conn)
            net["connections"] = normalized_conns

        return tpl

    @staticmethod
    def _build_circuit_from_dict(
        template_dict: Dict[str, Any],
        *,
        parameters: Optional[Dict[str, Dict[str, Any]]] = None,
        custom_name: Optional[str] = None,
    ) -> Circuit:
        """Convert template dictionary → Circuit entity."""
        parameters = parameters or {}

        # ---------- Components ----------
        components_dict: Dict[str, Component] = {}
        for comp_def in template_dict.get("components", []):
            comp_id = comp_def["id"]

            # Merge / override parameters
            comp_params = dict(comp_def.get("parameters", {}))
            if comp_id in parameters:
                comp_params.update(parameters[comp_id])

            # Wrap raw values → ParameterValue
            param_values: Dict[str, ParameterValue] = {}
            for key, value in comp_params.items():
                if isinstance(value, ParameterValue):
                    param_values[key] = value
                else:
                    param_values[key] = ParameterValue(value=value)

            # Resolve ComponentType
            raw_type = comp_def.get("_normalized_type", comp_def.get("type", ""))
            try:
                comp_type = ComponentType.normalize(raw_type)
            except ValueError:
                comp_type = ComponentType.CONNECTOR  # fallback

            # Pins → tuple
            pins = comp_def.get("pins", [])
            if isinstance(pins, list):
                pins = tuple(pins)

            # KiCad metadata
            kicad = comp_def.get("kicad", {})
            position = comp_def.get("position", {"x": 0, "y": 0})

            component = Component(
                id=comp_id,
                type=comp_type,
                pins=pins,
                parameters=param_values,
                library_id=kicad.get("library_id"),
                symbol_name=kicad.get("symbol_name"),
                footprint=kicad.get("footprint"),
                symbol_version=kicad.get("symbol_version", "1.0"),
                render_style={"position": position},
            )
            components_dict[comp_id] = component

        # ---------- Nets ----------
        nets_dict: Dict[str, Net] = {}
        for net_def in template_dict.get("nets", []):
            pin_refs = []
            for conn in net_def.get("connections", []):
                if isinstance(conn, (list, tuple)) and len(conn) == 2:
                    pin_refs.append(PinRef(component_id=conn[0], pin_name=conn[1]))
            nets_dict[net_def["id"]] = Net(
                name=net_def["id"],
                connected_pins=tuple(pin_refs),
            )

        # ---------- Ports ----------
        ports_dict: Dict[str, Port] = {}
        for port_def in template_dict.get("ports", []):
            direction = None
            dir_str = port_def.get("direction", "")
            if dir_str:
                try:
                    direction = PortDirection(dir_str.lower())
                except ValueError:
                    direction = None
            ports_dict[port_def["id"]] = Port(
                name=port_def["id"],
                net_name=port_def.get("net", ""),
                direction=direction,
            )

        # ---------- Constraints ----------
        constraints_dict: Dict[str, Constraint] = {}
        for idx, cst in enumerate(template_dict.get("constraints", [])):
            cname = f"{cst.get('type', 'constraint')}_{cst.get('target', idx)}"
            # Trích xuất structured fields từ JSON constraint
            cst_type = cst.get("type")
            cst_target = cst.get("target")
            cst_min = cst.get("min") if cst.get("min") is not None else cst.get("min_watts")
            cst_max = cst.get("max")
            constraints_dict[cname] = Constraint(
                name=cname,
                value=cst,
                constraint_type=cst_type,
                target=cst_target,
                min_value=float(cst_min) if cst_min is not None else None,
                max_value=float(cst_max) if cst_max is not None else None,
            )

        # ---------- Template metadata ----------
        topology_type = template_dict.get("topology_type")
        category = template_dict.get("category")
        template_id = template_dict.get("template_id")
        tags_raw = template_dict.get("tags", [])
        tags = tuple(tags_raw) if isinstance(tags_raw, list) else ()
        description = template_dict.get("description")
        parametric = template_dict.get("parametric")
        pcb_hints = template_dict.get("pcb_hints")

        # ---------- Circuit ----------
        return Circuit(
            id=str(uuid.uuid4()),
            name=custom_name or description or "Circuit from template",
            _components=components_dict,
            _nets=nets_dict,
            _ports=ports_dict,
            _constraints=constraints_dict,
            topology_type=topology_type,
            category=category,
            template_id=template_id,
            tags=tags,
            description=description,
            parametric=parametric,
            pcb_hints=pcb_hints,
        )


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------
_loader: Optional[TemplatesLoader] = None


def get_loader(templates_dir: str | Path | None = None) -> TemplatesLoader:
    """Trả về singleton TemplatesLoader, tự động load lần đầu.

    Parameters
    ----------
    templates_dir : optional
        Override đường dẫn templates (chủ yếu cho testing).

    Returns
    -------
    TemplatesLoader
    """
    global _loader
    if _loader is None:
        _loader = TemplatesLoader(templates_dir)
    return _loader
