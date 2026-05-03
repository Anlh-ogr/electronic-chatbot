"""Export circuit to KiCad schematic use case.

This module implements the business logic for exporting circuits to
KiCad .kicad_sch format and storing artifacts.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

try:
    import networkx as nx
except Exception:  # pragma: no cover - optional dependency guard
    nx = None

from app.application.ai.circuit_ir_schema import CircuitIR
from app.domains.circuits.entities import Circuit
from app.application.circuits.ports import (
    CircuitRepositoryPort,
    ExporterPort,
)
from app.application.circuits.dtos import (
    ExportCircuitRequest,
    ExportFormat,
    ExportCircuitResponse,
)
from app.application.circuits.errors import (
    CircuitNotFoundError,
    ExportError,
    StorageError,
)

logger = logging.getLogger(__name__)


class ExportKiCadSchUseCase:
    """Use case for exporting circuits to KiCad schematic format.
    
    This use case:
    1. Retrieves circuit from repository
    2. Optionally validates circuit before export
    3. Exports to .kicad_sch format
    4. Stores artifact to filesystem
    5. Returns download URL/path
    """
    
    def __init__(
        self,
        repository: CircuitRepositoryPort,
        exporter: ExporterPort,
        storage_path: Path,
        oracle_validator: Optional[Any] = None,
    ):
        """Initialize use case with dependencies.
        
        Args:
            repository: Circuit repository for retrieval
            exporter: Exporter service for format conversion
            storage_path: Base path for storing exported files
        """
        self.repository = repository
        self.exporter = exporter
        self.storage_path = storage_path
        self.oracle_validator = oracle_validator
        
        # Ensure storage path exists
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    async def execute(
        self,
        request: ExportCircuitRequest
    ) -> ExportCircuitResponse:
        """Execute circuit export to KiCad schematic.
        
        Args:
            request: Export request with circuit ID and options
            
        Returns:
            ExportCircuitResponse with file path and metadata
            
        Raises:
            CircuitNotFoundError: If circuit not found
            ExportError: If export fails
            StorageError: If file save fails
        """
        try:
            # Get circuit
            circuit = await self._get_circuit(request.circuit_id)

            # SCH debug: log circuit shape received by use case
            try:
                cid = request.circuit_id or (circuit.id if getattr(circuit, 'id', None) else None)
            except Exception:
                cid = request.circuit_id
            logger.info(
                "[SCH DEBUG] UseCase fetched circuit_id=%s components=%d nets=%d",
                cid,
                len(getattr(circuit, 'components', {})),
                len(getattr(circuit, 'nets', {})),
            )
            # Debug: component/net counts and source inference
            component_count = len(getattr(circuit, 'components', {}))
            net_count = len(getattr(circuit, 'nets', {}))
            repo_name = getattr(self.repository, '__class__', type(self.repository)).__name__
            if 'Postgres' in repo_name:
                source = 'postgres'
            elif 'Memory' in repo_name or 'InMemory' in repo_name:
                source = 'memory'
            else:
                source = repo_name
            logger.debug(
                "Export start: circuit=%s component_count=%d net_count=%d source=%s",
                request.circuit_id,
                component_count,
                net_count,
                source,
            )

            # Fail fast on empty circuit
            if component_count == 0 or net_count == 0:
                raise ExportError(
                    format_type=request.format.value,
                    reason=f"Empty circuit: components={component_count}, nets={net_count}",
                )
            
            # Validate format
            if request.format != ExportFormat.KICAD:
                raise ExportError(
                    format_type=request.format.value,
                    reason="This use case only supports KiCad schematic export"
                )
            
            # Export to KiCad format
            kicad_content = await self.exporter.export(
                circuit=circuit,
                format_type=ExportFormat.KICAD
            )
            
            # Generate filename
            filename = self._generate_filename(circuit, request)
            
            # Save to storage
            file_path = await self._save_artifact(filename, kicad_content)

            # Log artifact info
            try:
                logger.debug("Export finished: file=%s size=%d", str(file_path), file_path.stat().st_size)
            except Exception:
                logger.debug("Export finished: file=%s", str(file_path))

            oracle_report = await self._run_oracle_validation(
                file_path=file_path,
                options=request.options,
            )

            layout_quality = self._extract_layout_quality_metadata()
            
            # Calculate file size
            file_size = len(kicad_content.encode('utf-8'))

            metadata: dict[str, Any] = {
                "circuit_name": circuit.name or "Unnamed",
                "component_count": len(circuit.components),
                "kicad_version": "8.0",  # Target KiCad version
                "oracle": oracle_report,
            }
            if layout_quality is not None:
                metadata["layout_quality"] = layout_quality
            
            return ExportCircuitResponse(
                circuit_id=request.circuit_id,
                format=request.format,
                file_path=str(file_path),
                file_size=file_size,
                download_url=f"/api/circuits/{request.circuit_id}/exports/{filename}",
                metadata=metadata,
            )
            
        except CircuitNotFoundError:
            raise
        except ExportError:
            raise
        except Exception as e:
            raise ExportError(
                format_type=request.format.value,
                reason=str(e)
            ) from e
    
    async def _get_circuit(self, circuit_id: str) -> Circuit:
        """Retrieve circuit from repository.
        
        Args:
            circuit_id: Circuit identifier
            
        Returns:
            Circuit entity
            
        Raises:
            CircuitNotFoundError: If circuit not found
        """
        circuit = await self.repository.get(circuit_id)
        if not circuit:
            raise CircuitNotFoundError(circuit_id)
        return circuit
    
    def _generate_filename(
        self,
        circuit: Circuit,
        request: ExportCircuitRequest
    ) -> str:
        """Generate filename for exported file.
        
        Args:
            circuit: Circuit entity
            request: Export request
            
        Returns:
            Filename string
        """
        # Use circuit name or ID
        base_name = circuit.name or circuit.id

        if not base_name:
            base_name = request.circuit_id
        
        # Sanitize filename
        safe_name = "".join(c for c in base_name if c.isalnum() or c in "._- ")
        safe_name = safe_name.replace(" ", "_")
        
        # Add format extension
        extension = ".kicad_sch"

        suffix = (circuit.id or request.circuit_id or str(uuid.uuid4()))[:8]
        return f"{safe_name}_{suffix}{extension}"
    
    async def _save_artifact(
        self,
        filename: str,
        content: str
    ) -> Path:
        """Save exported content to filesystem.
        
        Args:
            filename: Name of file to save
            content: File content
            
        Returns:
            Path to saved file
            
        Raises:
            StorageError: If save fails
        """
        try:
            file_path = self.storage_path / filename
            
            # Write content
            file_path.write_text(content, encoding='utf-8')
            
            return file_path
            
        except Exception as e:
            raise StorageError(
                operation="write",
                path=str(file_path),
                reason=str(e)
            ) from e

    async def _run_oracle_validation(
        self,
        file_path: Path,
        options: Dict[str, Any],
    ) -> Dict[str, Any]:
        enabled = bool(options.get("oracle_validate", False))
        strict = bool(options.get("oracle_strict", False))

        if not enabled:
            return {
                "target": "schematic",
                "enabled": False,
                "strict": strict,
                "status": "skipped",
                "available": False,
                "passed": False,
                "backend": "kicad-cli",
                "message": "oracle validation disabled",
            }

        if self.oracle_validator is None:
            report = {
                "target": "schematic",
                "enabled": True,
                "strict": strict,
                "status": "unavailable",
                "available": False,
                "passed": False,
                "backend": "kicad-cli",
                "message": "oracle validator not configured",
            }
            if strict:
                raise ExportError(
                    format_type=ExportFormat.KICAD.value,
                    reason="Oracle validation failed in strict mode: validator unavailable",
                )
            return report

        try:
            result = await self.oracle_validator.validate_schematic(file_path)
            report = result.to_dict() if hasattr(result, "to_dict") else dict(result)
            report["enabled"] = True
            report["strict"] = strict

            if strict and report.get("status") != "passed":
                raise ExportError(
                    format_type=ExportFormat.KICAD.value,
                    reason=(
                        "Oracle validation failed in strict mode: "
                        f"{report.get('message', 'unknown error')}"
                    ),
                )

            return report
        except ExportError:
            raise
        except Exception as exc:
            report = {
                "target": "schematic",
                "enabled": True,
                "strict": strict,
                "status": "error",
                "available": True,
                "passed": False,
                "backend": "kicad-cli",
                "message": f"oracle validation error: {exc}",
            }
            if strict:
                raise ExportError(
                    format_type=ExportFormat.KICAD.value,
                    reason=(
                        "Oracle validation failed in strict mode: "
                        f"{report['message']}"
                    ),
                )
            return report

    def _extract_layout_quality_metadata(self) -> Optional[Dict[str, Any]]:
        getter = getattr(self.exporter, "get_last_layout_quality_report", None)
        if not callable(getter):
            return None

        result = getter()
        if result is None:
            return None
        if hasattr(result, "to_dict"):
            return result.to_dict()
        if isinstance(result, dict):
            return dict(result)
        return None


class KiCad8SchematicCompiler:
    """Compile validated CircuitIR to minimal KiCad 8 schematic s-expression."""

    GRID_STEP = 50.0

    _LIB_ID_MAP: Dict[str, str] = {
        "resistor": "Device:R",
        "capacitor": "Device:C",
        "inductor": "Device:L",
        "npn": "Device:Q_NPN_BCE",
        "pnp": "Device:Q_PNP_BCE",
        "diode": "Device:D",
        "voltage_source": "Device:V",
        "current_source": "Device:I",
        "opamp": "Amplifier_Operational:LM741",
        "power_symbol": "power:VCC",
    }

    _TYPE_ALIASES: Dict[str, str] = {
        "r": "resistor",
        "res": "resistor",
        "resistor": "resistor",
        "c": "capacitor",
        "cap": "capacitor",
        "capacitor": "capacitor",
        "l": "inductor",
        "inductor": "inductor",
        "q_npn": "npn",
        "bjt_npn": "npn",
        "npn": "npn",
        "q_pnp": "pnp",
        "bjt_pnp": "pnp",
        "pnp": "pnp",
        "diode": "diode",
        "d": "diode",
        "voltage_source": "voltage_source",
        "vsource": "voltage_source",
        "current_source": "current_source",
        "isource": "current_source",
        "opamp": "opamp",
        "op_amp": "opamp",
        "power_symbol": "power_symbol",
    }

    _PIN_OFFSETS: Dict[str, Dict[str, Tuple[float, float]]] = {
        "resistor": {"1": (-25.0, 0.0), "2": (25.0, 0.0)},
        "capacitor": {"1": (-25.0, 0.0), "2": (25.0, 0.0)},
        "inductor": {"1": (-25.0, 0.0), "2": (25.0, 0.0)},
        "diode": {"1": (-25.0, 0.0), "2": (25.0, 0.0), "A": (-25.0, 0.0), "K": (25.0, 0.0)},
        "npn": {
            "B": (-25.0, 0.0),
            "C": (0.0, -25.0),
            "E": (0.0, 25.0),
            "1": (-25.0, 0.0),
            "2": (0.0, -25.0),
            "3": (0.0, 25.0),
        },
        "pnp": {
            "B": (-25.0, 0.0),
            "C": (0.0, -25.0),
            "E": (0.0, 25.0),
            "1": (-25.0, 0.0),
            "2": (0.0, -25.0),
            "3": (0.0, 25.0),
        },
        "voltage_source": {"+": (0.0, -25.0), "-": (0.0, 25.0), "1": (0.0, -25.0), "2": (0.0, 25.0)},
        "current_source": {"+": (0.0, -25.0), "-": (0.0, 25.0), "1": (0.0, -25.0), "2": (0.0, 25.0)},
        "opamp": {
            "IN+": (-35.0, -20.0),
            "IN-": (-35.0, 20.0),
            "OUT": (35.0, 0.0),
            "V+": (0.0, -35.0),
            "V-": (0.0, 35.0),
            "3": (-35.0, -20.0),
            "2": (-35.0, 20.0),
            "6": (35.0, 0.0),
            "7": (0.0, -35.0),
            "4": (0.0, 35.0),
        },
    }

    def _calculate_placement(self, ir: CircuitIR) -> Dict[str, Tuple[float, float]]:
        """Calculate schematic coordinates with networkx layout algorithms."""
        refs = [comp.ref_id.strip().upper() for comp in ir.components if comp.ref_id.strip()]
        if not refs:
            return {}

        if nx is None:
            logger.warning("networkx unavailable; using deterministic fallback placement")
            return self._fallback_line_placement(refs)

        graph = nx.Graph()
        for ref in refs:
            graph.add_node(ref)

        for net in ir.nets:
            net_refs: List[str] = []
            for node in net.nodes:
                if ":" not in node:
                    continue
                ref = node.split(":", 1)[0].strip().upper()
                if ref in graph and ref not in net_refs:
                    net_refs.append(ref)

            if len(net_refs) < 2:
                continue

            anchor = net_refs[0]
            for other in net_refs[1:]:
                graph.add_edge(anchor, other, net=net.net_name)

        try:
            if graph.number_of_edges() > 0 and hasattr(nx, "nx_agraph"):
                raw_layout = nx.nx_agraph.graphviz_layout(graph, prog="dot")
            else:
                raw_layout = nx.spring_layout(graph, seed=42)
        except Exception as exc:
            logger.warning("graph layout failed (%s). Falling back to spring layout.", exc)
            try:
                raw_layout = nx.spring_layout(graph, seed=42)
            except Exception:
                return self._fallback_line_placement(refs)

        return self._normalize_layout_to_grid(raw_layout)

    def compile_to_sch(self, ir: CircuitIR) -> str:
        """Compile CircuitIR into a minimal valid KiCad 8 schematic string."""
        from app.application.ai.kicad_symbol_library import get_kicad_symbol_mapper
        
        placements = self._calculate_placement(ir)
        power_counter = 0
        comp_by_ref = {comp.ref_id.strip().upper(): comp for comp in ir.components}

        lines: List[str] = [
            '(kicad_sch (version 20231120) (generator "AI_Compiler")',
            f'  (uuid "{uuid.uuid4().hex}")',
            '  (paper "A4")',
            '  (lib_symbols)',
        ]

        mapper = get_kicad_symbol_mapper()

        for comp in ir.components:
            ref = comp.ref_id.strip().upper()
            x, y = placements.get(ref, (100.0, 100.0))
            
            # Strategy: Use kicad_symbol field if available, else resolve from component value/type
            is_power_symbol = str(comp.type or "").strip().lower() == "power_symbol"
            if is_power_symbol:
                if ref in {"GND", "GROUND", "VSS", "VEE", "0"}:
                    lib_id = "power:GND"
                else:
                    lib_id = "power:VCC"
                power_counter += 1
                ref_tag = f"#PWR{power_counter:02d}"
            elif comp.kicad_symbol and comp.kicad_symbol.strip():
                lib_id = comp.kicad_symbol.strip()
            else:
                # Try resolving from component value (model name)
                lib_id = mapper.lookup_by_model(str(comp.value or ""))
                if not lib_id:
                    # Fall back to type-based resolution
                    lib_id = self._resolve_lib_id(comp.type, ref)
            
            ref_label = self._escape_text(ref)
            value_label = self._escape_text(str(comp.value))
            footprint = "" if is_power_symbol else self._escape_text(comp.footprint or "")

            symbol_lines = []
            # Header line
            symbol_lines.append(f'  (symbol (lib_id "{lib_id}") (at {x:.3f} {y:.3f} 0) (unit 1) (in_bom yes) (on_board yes) (uuid "{uuid.uuid4().hex}" )')
            # Reference and Value
            if is_power_symbol:
                symbol_lines.append(f'    (property "Reference" "{ref_tag}" (at {x:.3f} {y - 20.0:.3f} 0) (effects (font (size 1.27 1.27)) hide))')
                symbol_lines.append(f'    (property "Value" "{value_label}" (at {x:.3f} {y + 20.0:.3f} 0) (effects (font (size 1.27 1.27))))')
                # Ensure a single pin "1" for power symbols
                symbol_lines.append(f'    (pin "1" (uuid "{uuid.uuid4().hex}"))')
            else:
                symbol_lines.append(f'    (property "Reference" "{ref_label}" (at {x:.3f} {y - 20.0:.3f} 0) (effects (font (size 1.27 1.27))))')
                symbol_lines.append(f'    (property "Value" "{value_label}" (at {x:.3f} {y + 20.0:.3f} 0) (effects (font (size 1.27 1.27))))')
                if not is_power_symbol:
                    symbol_lines.append(f'    (property "Footprint" "{footprint}" (at {x:.3f} {y:.3f} 0) (effects (font (size 1.27 1.27)) hide))')
            # Close symbol block
            symbol_lines.append('  )')
            lines.extend(symbol_lines)

        for net in ir.nets:
            points: List[Tuple[float, float]] = []
            for node in net.nodes:
                if ":" not in node:
                    continue
                raw_ref, raw_pin = node.split(":", 1)
                ref = raw_ref.strip().upper()
                comp = comp_by_ref.get(ref)
                if comp is None:
                    continue
                points.append(self._resolve_pin_position(ref, raw_pin.strip(), comp.type, placements))

            if len(points) < 2:
                continue

            anchor = points[0]
            for point in points[1:]:
                lines.append(
                    f'  (wire (pts (xy {anchor[0]:.3f} {anchor[1]:.3f}) (xy {point[0]:.3f} {point[1]:.3f})) '
                    f'(stroke (width 0) (type default)) (uuid "{uuid.uuid4().hex}"))'
                )

        lines.append(')')
        return "\n".join(lines) + "\n"

    def _normalize_layout_to_grid(self, layout: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
        xs = [float(pos[0]) for pos in layout.values()]
        ys = [float(pos[1]) for pos in layout.values()]

        min_x = min(xs) if xs else 0.0
        max_x = max(xs) if xs else 1.0
        min_y = min(ys) if ys else 0.0
        max_y = max(ys) if ys else 1.0

        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)

        normalized: Dict[str, Tuple[float, float]] = {}
        for ref, pos in layout.items():
            px = float(pos[0])
            py = float(pos[1])

            sx = 100.0 + ((px - min_x) / span_x) * 800.0
            sy = 100.0 + ((py - min_y) / span_y) * 600.0

            gx = round(sx / self.GRID_STEP) * self.GRID_STEP
            gy = round(sy / self.GRID_STEP) * self.GRID_STEP
            normalized[str(ref).upper()] = (gx, gy)

        return normalized

    def _fallback_line_placement(self, refs: List[str]) -> Dict[str, Tuple[float, float]]:
        placement: Dict[str, Tuple[float, float]] = {}
        cols = max(1, int(math.sqrt(len(refs))))
        for idx, ref in enumerate(refs):
            row = idx // cols
            col = idx % cols
            placement[ref] = (
                100.0 + col * 200.0,
                100.0 + row * 200.0,
            )
        return placement

    def _resolve_lib_id(self, comp_type: str, comp_id: str = "") -> str:
        raw = str(comp_type or "").strip().lower()
        comp_id_norm = str(comp_id or "").strip().upper()
        if raw == "power_symbol":
            if comp_id_norm in {"GND", "GROUND", "VSS", "VEE", "0"}:
                return "power:GND"
            return "power:VCC"
        canonical = self._TYPE_ALIASES.get(raw)
        if canonical is None:
            for key, alias in self._TYPE_ALIASES.items():
                if key in raw:
                    canonical = alias
                    break
        if canonical is None:
            canonical = "resistor"
        return self._LIB_ID_MAP.get(canonical, "Device:R")

    def _resolve_pin_position(
        self,
        ref: str,
        pin: str,
        component_type: str,
        placement: Dict[str, Tuple[float, float]],
    ) -> Tuple[float, float]:
        base = placement.get(ref.upper(), (100.0, 100.0))
        canonical = self._resolve_type_alias(component_type)
        pin_map = self._PIN_OFFSETS.get(canonical, {})
        offset = pin_map.get(pin.strip().upper())
        if offset is None:
            # Generic fallback for unknown pin names.
            if pin.strip() == "1":
                offset = (-25.0, 0.0)
            elif pin.strip() == "2":
                offset = (25.0, 0.0)
            else:
                offset = (0.0, 0.0)

        return (base[0] + offset[0], base[1] + offset[1])

    def _resolve_type_alias(self, component_type: str) -> str:
        raw = str(component_type or "").strip().lower()
        canonical = self._TYPE_ALIASES.get(raw)
        if canonical is not None:
            return canonical
        for key, alias in self._TYPE_ALIASES.items():
            if key in raw:
                return alias
        return "resistor"

    @staticmethod
    def _escape_text(text: str) -> str:
        return str(text or "").replace('"', "")
