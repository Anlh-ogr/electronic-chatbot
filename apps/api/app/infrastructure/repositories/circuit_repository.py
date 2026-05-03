# .\\thesis\\electronic-chatbot\\apps\\api\\app\\infrastructure\\repositories\\circuit_repository.py
"""Triển khai PostgreSQL Repository cho Mạch điện (Circuits).

Module này cung cấp adapter PostgreSQL cho circuit persistence. Nó quản lý
lưu trữ, truy vấn mạch điện bao gồm serialization IR, version management,
và circuit metadata (name, description, created_by).

Vietnamese:
- Trách nhiệm: Quản lý lưu trữ mạch điện trong PostgreSQL
- Chức năng: Save/update circuits, get by ID, list, serialize IR
- Phụ thuộc: SQLAlchemy ORM, CircuitIRSerializer

English:
- Responsibility: Manage circuit persistence in PostgreSQL
- Features: Save/update circuits, get by ID, list, IR serialization
- Dependencies: SQLAlchemy ORM, CircuitIRSerializer
"""

# ====== Lý do sử dụng thư viện ======
# typing: Type hints cho IDE support
# sqlalchemy.orm: ORM session management
# sqlalchemy: Database queries + filtering
# uuid: Generate unique circuit IDs
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc, text
import uuid
import logging
import re

# ====== Domain & Application layers ======
from app.domains.circuits.entities import Circuit
from app.domains.circuits.ir import CircuitIRSerializer

# ====== Database models ======
from app.db.models import CircuitModel, SnapshotModel


logger = logging.getLogger(__name__)


# ====== PostgreSQL Circuit Repository Implementation ======
class PostgresCircuitRepository:
    """Triển khai PostgreSQL Repository cho Circuit entities.
    
    Class này quản lý circuit persistence với CircuitIRSerializer,
    hỗ trợ save/update, retrieval, listing, và IR (Intermediate Representation) management.
    
    Responsibilities (Trách nhiệm):
    - Lưu/cập nhật circuits vào PostgreSQL
    - Truy vấn circuits theo ID hoặc criteria
    - Serialize circuits thành IR for persistence
    - Maintain circuit metadata (name, description, created_by)
    """
    
    def __init__(self, session: Session):
        """Initialize repository.
        
        Args:
            session: SQLAlchemy session
        """
        self.session = session
    
    async def save(
        self,
        circuit: Circuit,
        circuit_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        created_by: str = "system"
    ) -> str:
        """Save circuit to database.
        
        Args:
            circuit: Circuit entity
            circuit_id: Optional ID (generates if not provided)
            name: Circuit name
            description: Circuit description
            created_by: Creator identifier
            
        Returns:
            Circuit ID
        """
        cid = circuit_id or str(uuid.uuid4())
        
        # Serialize circuit
        ir = CircuitIRSerializer.build_ir(circuit, circuit_id=cid)
        ir_data = CircuitIRSerializer.to_dict(ir)
        
        _ = created_by  # compatibility placeholder

        # Check if exists
        existing = self.session.query(CircuitModel).filter(
            CircuitModel.circuit_id == cid
        ).first()
        
        if existing:
            # Update
            existing.name = name or circuit.name or existing.name
            existing.description = description or existing.description
        else:
            # Create
            model = CircuitModel(
                circuit_id=cid,
                name=name or circuit.name or "Unnamed Circuit",
                description=description or "",
            )
            self.session.add(model)

        # Persist latest circuit IR into snapshots table (Neon schema source of truth).
        if ir_data is None:
            logger.error("Attempting to save NULL ir_data for circuit: %s; aborting snapshot insert", cid)
            self.session.commit()
            return cid

        snapshot_model = SnapshotModel(
            snapshot_id=str(uuid.uuid4()),
            circuit_id=cid,
            message_id=None,
            circuit_data=ir_data,
        )
        self.session.add(snapshot_model)
        
        self.session.commit()
        return cid
    
    async def get_by_id(self, circuit_id: str) -> Optional[Circuit]:
        """Get circuit by ID.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            Circuit entity if found, None otherwise
        """
        model = self.session.query(CircuitModel).filter(
            CircuitModel.circuit_id == circuit_id
        ).first()

        latest_snapshot = (
            self.session.query(SnapshotModel)
            .filter(SnapshotModel.circuit_id == circuit_id)
            .order_by(desc(SnapshotModel.created_at), desc(SnapshotModel.snapshot_id))
            .first()
        )

        default_name = (model.name if model is not None else None) or "Unnamed Circuit"

        payload = None
        if latest_snapshot is not None:
            payload = latest_snapshot.circuit_data
            if payload is None or (isinstance(payload, str) and not payload.strip()) or (
                isinstance(payload, (dict, list, tuple, set)) and len(payload) == 0
            ):
                logger.critical(
                    "Snapshot payload is completely missing or null in Postgres for circuit_id: %s",
                    circuit_id,
                )
                payload = None
            elif not isinstance(payload, dict):
                logger.critical(
                    "Snapshot payload is completely missing or null in Postgres for circuit_id: %s",
                    circuit_id,
                )
                payload = None

        if payload is not None:
            # First try canonical IR snapshot.
            try:
                ir = CircuitIRSerializer.from_dict(payload)
                return ir.circuit
            except Exception as exc:
                logger.warning("Circuit %s has non-canonical snapshot payload: %s", circuit_id, exc)

            # Fallback: hydrate from chatbot/compiled payload shape into canonical IR dict.
            try:
                coerced = self._coerce_snapshot_to_ir_dict(
                    payload=payload,
                    circuit_id=circuit_id,
                    default_name=default_name,
                )
                if coerced is None:
                    return None
                return CircuitIRSerializer.to_circuit(coerced)
            except Exception as exc:
                logger.warning("Circuit %s fallback snapshot coercion failed: %s", circuit_id, exc)
                return None

        # Final fallback: some flows persist canonical CircuitIR into circuit_irs instead of snapshots.
        try:
            row = (
                self.session.execute(
                    text(
                        """
                        SELECT ir_json, circuit_name, topology_type
                        FROM circuit_irs
                        WHERE circuit_id = :circuit_id
                        ORDER BY created_at DESC
                        LIMIT 1
                        """
                    ),
                    {"circuit_id": circuit_id},
                )
            ).mappings().first()
            if row is None:
                logger.warning("Circuit %s not found in repository!", circuit_id)
                return None

            ir_json = row.get("ir_json")
            if not isinstance(ir_json, dict):
                logger.warning("Circuit %s circuit_irs payload is not a dict", circuit_id)
                return None

            coerced = self._coerce_snapshot_to_ir_dict(
                payload=ir_json,
                circuit_id=circuit_id,
                default_name=str(row.get("circuit_name") or default_name or "Unnamed Circuit"),
            )
            if coerced is None:
                logger.warning("Circuit %s circuit_irs fallback coercion returned no payload", circuit_id)
                return None

            logger.info("Loaded circuit %s from circuit_irs fallback", circuit_id)
            return CircuitIRSerializer.to_circuit(coerced)
        except Exception as exc:
            logger.warning("Circuit %s circuit_irs fallback lookup failed: %s", circuit_id, exc)
            return None

    @staticmethod
    def _normalize_component_type(raw_type: Any) -> str:
        text = str(raw_type or "").strip().lower()
        if text in {"power", "pwr", "vcc", "vdd", "vss", "vee", "vccg"}:
            return "voltage_source"
        if text in {"power_port", "pwr_port", "vcc_port", "gnd_port"}:
            return "port"
        if text in {"gnd", "ground", "0"}:
            return "ground"
        if text in {"op-amp", "op_amp", "opamp", "op amp"}:
            return "opamp"
        return text or "resistor"

    @staticmethod
    def _coerce_snapshot_to_ir_dict(
        payload: Any,
        circuit_id: str,
        default_name: str,
    ) -> Optional[Dict[str, Any]]:
        if payload is None or (isinstance(payload, str) and not payload.strip()) or (
            isinstance(payload, (dict, list, tuple, set)) and len(payload) == 0
        ):
            logger.critical(
                "Snapshot payload is completely missing or null in Postgres for circuit_id: %s",
                circuit_id,
            )
            return None

        if not isinstance(payload, dict):
            return None

        # Already canonical enough for CircuitIRSerializer.to_circuit.
        if all(key in payload for key in ("meta", "components", "nets", "ports", "constraints")):
            return payload

        components_raw = payload.get("components")
        nets_raw = payload.get("nets")
        if not isinstance(components_raw, list) or not isinstance(nets_raw, list):
            return None

        ir_components: List[Dict[str, Any]] = []
        pins_by_component: Dict[str, List[str]] = {}

        ir_nets: List[Dict[str, Any]] = []
        for idx, net in enumerate(nets_raw):
            if not isinstance(net, dict):
                continue

            connected_pins: List[Dict[str, str]] = []
            net_nodes = list(net.get("nodes", []) or [])
            net_connections = list(net.get("connections", []) or [])
            if net_nodes and not net_connections:
                for node in net_nodes:
                    text = str(node or "").strip()
                    if ":" not in text:
                        continue
                    ref, pin = text.split(":", 1)
                    net_connections.append([ref.strip(), pin.strip()])

            for conn in net_connections:
                if isinstance(conn, list) and len(conn) >= 2:
                    comp_id = str(conn[0] or "").strip()
                    pin_name = str(conn[1] or "").strip()
                elif isinstance(conn, dict):
                    comp_id = str(conn.get("component_id") or conn.get("component") or "").strip()
                    pin_name = str(conn.get("pin_name") or conn.get("pin") or "").strip()
                else:
                    continue

                if not comp_id or not pin_name:
                    continue
                connected_pins.append({"component_id": comp_id, "pin_name": pin_name})
                pins_by_component.setdefault(comp_id, [])
                if pin_name not in pins_by_component[comp_id]:
                    pins_by_component[comp_id].append(pin_name)

            if not connected_pins:
                continue

            raw_name = net.get("name") or net.get("net_name") or net.get("id") or f"NET_{idx+1}"
            net_name = str(raw_name or "").strip() or f"NET_{idx+1}"
            ir_nets.append({"name": net_name, "connected_pins": connected_pins})

        single_pin_types = {"connector", "port", "ground", "voltage_source", "current_source"}
        for comp in components_raw:
            if not isinstance(comp, dict):
                continue

            comp_id = str(comp.get("id") or comp.get("ref_id") or "").strip()
            if not comp_id:
                continue
            comp_type = PostgresCircuitRepository._normalize_component_type(comp.get("type"))

            source_params = dict(comp.get("parameters", {}) or {})
            if comp_type == "resistor" and "resistance" not in source_params:
                fallback = comp.get("resistance") or comp.get("standardized_value") or comp.get("value")
                if fallback not in (None, ""):
                    source_params["resistance"] = fallback
            elif comp_type in {"capacitor", "capacitor_polarized"} and "capacitance" not in source_params:
                fallback = comp.get("capacitance") or comp.get("standardized_value") or comp.get("value")
                if fallback not in (None, ""):
                    source_params["capacitance"] = fallback
            elif comp_type == "inductor" and "inductance" not in source_params:
                fallback = comp.get("inductance") or comp.get("standardized_value") or comp.get("value")
                if fallback not in (None, ""):
                    source_params["inductance"] = fallback
            elif comp_type == "voltage_source" and "voltage" not in source_params:
                fallback = comp.get("voltage") or comp.get("value") or comp.get("standardized_value")
                if fallback not in (None, ""):
                    source_params["voltage"] = fallback

            ir_params: Dict[str, Dict[str, Any]] = {}
            for key, value in source_params.items():
                if isinstance(value, dict) and "value" in value:
                    ir_params[key] = {
                        "value": str(value.get("value") if value.get("value") is not None else ""),
                        "unit": value.get("unit"),
                    }
                else:
                    ir_params[key] = {"value": str(value) if value is not None else ""}

            # Normalize pins into a list of strings. Accept formats: list, comma-separated string, dict, or missing.
            raw_pins = comp.get("pins")
            pins: List[str] = []
            if isinstance(raw_pins, list):
                pins = [str(p).strip() for p in raw_pins if p is not None and str(p).strip()]
            elif isinstance(raw_pins, str):
                # comma or space separated
                parts = [p.strip() for p in re.split(r"[,\s]+", raw_pins) if p.strip()]
                pins = parts
            elif isinstance(raw_pins, dict):
                # dict of pin_name -> meta
                pins = [str(k).strip() for k in raw_pins.keys() if str(k).strip()]

            if not pins:
                pins = list(pins_by_component.get(comp_id, []))

            if not pins:
                pins = ["1"] if comp_type in single_pin_types else ["1", "2"]

            # Ensure multi-pin components have at least two unique pins
            if comp_type not in single_pin_types:
                # remove empty and dedupe while preserving order
                seen = set()
                ordered = []
                for p in pins:
                    if p not in seen:
                        seen.add(p)
                        ordered.append(p)
                pins = ordered
                if len(pins) < 2:
                    if "2" not in pins:
                        pins.append("2")

            kicad_info = comp.get("kicad") if isinstance(comp.get("kicad"), dict) else {}
            ir_components.append(
                {
                    "id": comp_id,
                    "type": comp_type,
                    "pins": pins,
                    "parameters": ir_params,
                    "library_id": comp.get("library_id") or kicad_info.get("library_id"),
                    "symbol_name": comp.get("symbol_name") or kicad_info.get("symbol_name"),
                    "footprint": comp.get("footprint") or kicad_info.get("footprint"),
                    "symbol_version": comp.get("symbol_version") or kicad_info.get("symbol_version"),
                    "render_style": dict(comp.get("render_style", {}) or {}),
                }
            )

        # Add missing connector stubs referenced by nets.
        known_ids = {c["id"] for c in ir_components}
        for comp_id, inferred_pins in pins_by_component.items():
            if comp_id in known_ids:
                continue
            ir_components.append(
                {
                    "id": comp_id,
                    "type": "connector",
                    "pins": inferred_pins or ["1"],
                    "parameters": {},
                    "library_id": None,
                    "symbol_name": "Conn_01x01",
                    "footprint": None,
                    "symbol_version": None,
                    "render_style": {},
                }
            )

        ports_raw = payload.get("ports") if isinstance(payload.get("ports"), list) else []
        ir_ports = []
        for p in ports_raw:
            if not isinstance(p, dict):
                continue
            ir_ports.append(
                {
                    "name": p.get("name") or p.get("id") or "",
                    "net_name": p.get("net_name") or p.get("net") or "",
                    "direction": str(p.get("direction") or p.get("type") or "input").lower(),
                }
            )

        constraints_raw = payload.get("constraints") if isinstance(payload.get("constraints"), list) else []
        ir_constraints = [c for c in constraints_raw if isinstance(c, dict)]

        return {
            "meta": {
                "version": "1.0",
                "schema_version": "1.0",
                "circuit_id": circuit_id,
                "circuit_name": str(payload.get("name") or payload.get("topology_type") or default_name or "circuit"),
            },
            "components": ir_components,
            "nets": ir_nets,
            "ports": ir_ports,
            "constraints": ir_constraints,
            "topology_type": payload.get("topology_type"),
            "category": payload.get("category"),
            "tags": payload.get("tags", []),
        }
    
    async def list_all(self, limit: int = 100, offset: int = 0) -> List[dict]:
        """List all circuits with metadata.
        
        Args:
            limit: Maximum circuits to return
            offset: Offset for pagination
            
        Returns:
            List of circuit metadata dicts
        """
        models = self.session.query(CircuitModel).order_by(
            desc(CircuitModel.updated_at)
        ).limit(limit).offset(offset).all()
        
        return [
            {
                "id": m.circuit_id,
                "name": m.name,
                "description": m.description,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
                "created_by": "system"
            }
            for m in models
        ]
    
    async def delete(self, circuit_id: str) -> bool:
        """Delete circuit.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            True if deleted, False if not found
        """
        result = self.session.query(CircuitModel).filter(
            CircuitModel.circuit_id == circuit_id
        ).delete()
        self.session.commit()
        return result > 0
