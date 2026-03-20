# .\thesis\electronic-chatbot\apps\api\app\application\circuits\use_cases\generate_circuit.py
"""Generate circuit from template use case.

Module này chịu trách nhiệm:
 1. Orchestrate circuit generation workflow
 2. Load template từ templates_loader
 3. Substitute parameters (matching, solving nếu cần)
 4. Validate result qua domain rules
 5. Persist circuit qua repository
 6. Log toàn bộ flow để debug

Workflow:
 1. Validate request → GenerateFromTemplateRequest
 2. Load template → templates_loader.build_circuit()
 3. Parameter solving → ParameterSolver if needed
 4. Validate circuit → CircuitRulesEngine
 5. Save to repo → repository.save()
 6. Return CircuitResponse với circuit_data

Nguyên tắc:
 - Use case là orchestrator, không chứa business logic
 - Delegate đến domain classes (builders, validators, etc.)
 - Logging comprehensive để trace lỗi
 - Error handling explicit: catch domain exceptions, rethrow as ApplicationError
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
import uuid
from datetime import datetime
from enum import Enum

from app.domains.circuits.entities import Circuit
from app.domains.circuits.templates_loader import TemplatesLoader, get_loader
from app.application.circuits.ports import CircuitRepositoryPort
from app.application.circuits.dtos import (
    GenerateFromTemplateRequest,
    CircuitResponse,
)
from app.application.circuits.errors import TemplateGenerationError
from app.application.circuits.circuit_generation_logger import CircuitGenerationLogger


class TopologyType(Enum):
    """Supported topology types in domain."""
    # BJT Topologies
    BJT_COMMON_EMITTER = "bjt_common_emitter"
    BJT_COMMON_COLLECTOR = "bjt_common_collector"
    BJT_COMMON_BASE = "bjt_common_base"
    
    # MOSFET/FET Topologies
    MOSFET_COMMON_SOURCE = "mosfet_common_source"
    MOSFET_COMMON_DRAIN = "mosfet_common_drain"
    MOSFET_COMMON_GATE = "mosfet_common_gate"
    
    # OpAmp Topologies
    OPAMP_INVERTING = "opamp_inverting"
    OPAMP_NON_INVERTING = "opamp_non_inverting"
    OPAMP_DIFFERENTIAL = "opamp_differential"
    OPAMP_INSTRUMENTATION = "opamp_instrumentation"

    
    # Power Amplifier Classes
    POWER_CLASS_A = "power_class_a"
    POWER_CLASS_B = "power_class_b"
    POWER_CLASS_AB = "power_class_ab"
    POWER_CLASS_C = "power_class_c"
    POWER_CLASS_D = "power_class_d"
    
    # Special Topologies
    SPECIAL_DARLINGTON = "darlington_pair"
    SPECIAL_MULTISTAGE = "multi_stage_amplifier"


class ParameterValidator:
    """Domain-aware parameter validator."""
    
    # Required parameters per topology family
    REQUIRED_PARAMS = {
        "bjt": ["vcc"],
        "mosfet": ["vdd"],
        "opamp": ["vcc"],
        "power": ["vcc"],
        "special": ["vcc"],
    }
    
    # Valid ranges for common parameters
    PARAM_RANGES = {
        "vcc": (3.0, 50.0),
        "vdd": (3.0, 50.0),
        "vee": (-50.0, 0.0),
        "gain": (0.1, 1000.0),
        "frequency": (1.0, 1e9),
        "output_power": (0.1, 1000.0),
        "load_resistance": (1.0, 1e6),
    }
    
    @classmethod
    def validate_template_id(cls, template_id: str, loader: TemplatesLoader) -> None:
        """Validate template ID exists in domain.
        
        Args:
            template_id: Template identifier
            loader: Templates loader instance
            
        Raises:
            TemplateGenerationError: If template not found
        """
        template_id_lower = template_id.lower()
        
        if not loader.has(template_id_lower):
            # Try fuzzy search
            matches = loader.search(template_id_lower)
            if matches:
                suggestions = [m.get("topology_type", m.get("id")) for m in matches[:3]]
                raise TemplateGenerationError(
                    template_name=template_id,
                    reason=f"Template '{template_id}' không tồn tại. "
                           f"Có thể bạn muốn: {', '.join(suggestions)}? "
                           f"Tổng số {loader.count()} templates có sẵn."
                )
            else:
                raise TemplateGenerationError(
                    template_name=template_id,
                    reason=f"Template '{template_id}' không tồn tại. "
                           f"Dùng get_all_types() để xem {loader.count()} templates có sẵn."
                )
    
    @classmethod
    def validate_parameters(
        cls,
        template_id: str,
        parameters: Dict[str, Any],
        template_dict: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """Validate parameters against domain rules.
        
        Args:
            template_id: Template identifier
            parameters: User-provided parameters
            template_dict: Template definition from domain (optional)
            
        Returns:
            List of validation warnings (non-fatal)
        """
        warnings = []
        topology_family = cls._get_topology_family(template_id)
        
        # Check required parameters (relaxed - only critical ones)
        required = cls.REQUIRED_PARAMS.get(topology_family, [])
        missing = [p for p in required if p not in parameters and p.replace("vcc", "vdd") not in parameters]
        if missing:
            warnings.append(f"Thiếu tham số khuyến nghị cho topology '{topology_family}': {missing}")
        
        # Validate parameter ranges
        for param, value in parameters.items():
            if param in cls.PARAM_RANGES:
                if not isinstance(value, (int, float)):
                    continue
                min_val, max_val = cls.PARAM_RANGES[param]
                if not (min_val <= value <= max_val):
                    warnings.append(
                        f"Tham số '{param}'={value} nằm ngoài phạm vi khuyến nghị "
                        f"[{min_val}, {max_val}]"
                    )
        
        return warnings
    
    @staticmethod
    def parse_template_family_topology(template_id: str) -> tuple[str, str]:
        """
        Phân tích family (bjt, mosfet, opamp, power, special) và topology con từ template_id.
        Trả về (family, topology_subtype)
        """
        tid = template_id.lower()
        # Family
        if tid.startswith("bjt") or "bjt" in tid or "transistor" in tid:
            family = "bjt"
            # Topology con
            if "ce" in tid:
                subtype = "ce"
            elif "cc" in tid:
                subtype = "cc"
            elif "cb" in tid:
                subtype = "cb"
            else:
                subtype = "other"
        elif tid.startswith("mosfet") or "mosfet" in tid or "fet" in tid or "mos" in tid:
            family = "mosfet"
            if "cs" in tid:
                subtype = "cs"
            elif "cd" in tid:
                subtype = "cd"
            elif "cg" in tid:
                subtype = "cg"
            else:
                subtype = "other"
        elif tid.startswith("opamp") or "opamp" in tid or "op_amp" in tid or "op-amp" in tid:
            family = "opamp"
            if "inverting" in tid:
                subtype = "inverting"
            elif "non_inverting" in tid or "non-inverting" in tid:
                subtype = "non_inverting"
            elif "differential" in tid:
                subtype = "differential"
            elif "instrumentation" in tid:
                subtype = "instrumentation"
            else:
                subtype = "other"
        elif tid.startswith("power") or "power" in tid or "class" in tid or "power_amplifier" in tid or "power amp" in tid:
            family = "power"
            if "class_a" in tid or "class a" in tid:
                subtype = "class_a"
            elif "class_b" in tid or "class b" in tid:
                subtype = "class_b"
            elif "class_ab" in tid or "class ab" in tid:
                subtype = "class_ab"
            elif "class_c" in tid or "class c" in tid:
                subtype = "class_c"
            elif "class_d" in tid or "class d" in tid:
                subtype = "class_d"
            else:
                subtype = "other"
        elif tid.startswith("special") or "darlington" in tid or "multi" in tid or "stage" in tid:
            family = "special"
            if "darlington" in tid:
                subtype = "darlington"
            elif "multi_stage" in tid or "multi-stage" in tid or "multi stage" in tid:
                subtype = "multi_stage"
            else:
                subtype = "other"
        else:
            family = "unknown"
            subtype = "unknown"
        return family, subtype

    @staticmethod
    def _get_topology_family(template_id: str) -> str:
        """Extract topology family from template ID."""
        family, _ = ParameterValidator.parse_template_family_topology(template_id)
        return family


class GenerateCircuitUseCase:
    """Use case for generating circuits from templates - UPGRADED.
    
    This enhanced version:
    1. ✅ Validates all inputs against domain rules
    2. ✅ Supports all domain topologies (BJT, MOSFET, OpAmp, Power, Special)
    3. ✅ Leverages domain builders/factories with fallback strategy
    4. ✅ Comprehensive logging for debugging and traceability
    5. ✅ Proper error handling with detailed context
    6. ✅ Full metadata, tags, ports, nets mapping
    """
    
    def __init__(self, repository: CircuitRepositoryPort):
        """Initialize use case with repository dependency.
        
        Args:
            repository: Circuit repository for persistence
        """
        self.repository = repository
        self.logger = CircuitGenerationLogger()
        self.validator = ParameterValidator()
    
    async def execute(
        self,
        request: GenerateFromTemplateRequest,
        save: bool = True,
        prompt: Optional[str] = None
    ) -> CircuitResponse:
        """Execute circuit generation from template with full validation.
        
        Args:
            request: Template parameters and configuration
            save: Whether to save generated circuit to repository
            prompt: Original natural language prompt (for logging)
            
        Returns:
            CircuitResponse containing generated circuit data
            
        Raises:
            TemplateGenerationError: If generation fails
        """
        session_id = str(uuid.uuid4())
        start_time = datetime.now()
        
        # Log session start
        self.logger.log_info(
            session_id=session_id,
            message=f"Starting circuit generation: template={request.template_id}",
            metadata={
                "prompt": prompt,
                "parameters": request.parameters,
            }
        )
        
        try:
            # Step 1: Validate inputs and get warnings
            warnings = self._validate_inputs(request, session_id)
            
            # Step 2: Generate circuit using domain logic
            circuit = self._generate_from_template(
                template_id=request.template_id,
                parameters=request.parameters,
                session_id=session_id
            )
            
            # Step 3: Save if requested
            if save:
                saved_circuit = await self.repository.save(circuit)
                circuit = saved_circuit
                self.logger.log_info(
                    session_id=session_id,
                    message=f"Circuit saved: id={circuit.id}",
                )
            
            # Step 4: Log successful generation
            duration = (datetime.now() - start_time).total_seconds()
            generation_metadata = {
                "circuit_name": request.circuit_name,
                "circuit_description": request.circuit_description,
                "duration_seconds": duration,
                "component_count": len(circuit.components),
                "net_count": len(circuit.nets),
                "port_count": len(circuit.ports),
            }
            if warnings:
                generation_metadata["parameter_warnings"] = warnings
            
            self.logger.log_generation_session(
                session_id=session_id,
                prompt=prompt,
                template_id=request.template_id,
                parameters=request.parameters,
                circuit=circuit,
                metadata=generation_metadata
            )
            
            # Step 5: Convert to response DTO with warnings if any
            response = self._to_response(circuit, request, session_id)
            if warnings:
                response.metadata["parameter_warnings"] = warnings
            
            return response
            
        except TemplateGenerationError:
            raise
        
        except Exception as e:
            self.logger.log_error(
                session_id=session_id,
                error_type=type(e).__name__,
                message=str(e),
                metadata={
                    "template_id": request.template_id,
                    "parameters": request.parameters,
                }
            )
            raise TemplateGenerationError(
                template_name=request.template_id,
                reason=f"Lỗi không xác định: {str(e)}"
            ) from e
    
    def _validate_inputs(
        self,
        request: GenerateFromTemplateRequest,
        session_id: str
    ) -> list:
        """Validate request inputs against domain rules.
        
        Returns list of warnings (không raise nếu chỉ cảnh báo).
        """
        loader = get_loader()
        
        # Validate template exists (raise nếu không có template)
        self.validator.validate_template_id(request.template_id, loader)
        
        # Get template definition for parameter validation
        template_id_lower = request.template_id.lower()
        template_dict = None
        if loader.has(template_id_lower):
            template_dict = loader.get(template_id_lower)
        else:
            matches = loader.search(template_id_lower)
            if matches:
                template_dict = matches[0]
        
        warnings = []
        if template_dict:
            warnings = self.validator.validate_parameters(
                request.template_id,
                request.parameters,
                template_dict
            )
            if warnings:
                self.logger.log_warning(
                    session_id=session_id,
                    message="Parameter validation warnings",
                    metadata={"warnings": warnings}
                )
        
        return warnings
    
    def _generate_from_template(
        self,
        template_id: str,
        parameters: Dict[str, Any],
        session_id: str
    ) -> Circuit:
        """Generate circuit from template using domain builders.
        
        Strategy (priority order):
         1. TemplatesLoader (70+ JSON templates) — primary source
         2. Fuzzy search for similar templates
         3. Specialized builders — if needed in future
        
        Args:
            template_id: Template identifier
            parameters: Circuit parameters
            session_id: Logging session ID
            
        Returns:
            Generated Circuit entity
            
        Raises:
            TemplateGenerationError: If generation fails
        """
        loader = get_loader()
        template_id_lower = template_id.lower()
        
        # Get template from loader
        if not loader.has(template_id_lower):
            matches = loader.search(template_id_lower)
            if matches:
                template_dict = matches[0]
            else:
                raise TemplateGenerationError(
                    template_name=template_id,
                    reason=f"Template '{template_id}' không tồn tại."
                )
        else:
            template_dict = loader.get(template_id_lower)
        
        # Map flat parameters to component overrides
        param_overrides = self._map_flat_params_to_components(
            template_dict, parameters
        )
        
        custom_name = parameters.get("custom_name")
        topology = template_dict.get("topology_type", template_id_lower)
        
        self.logger.log_info(
            session_id=session_id,
            message=f"Building circuit: {custom_name}",
            metadata={
                "topology": topology,
                "param_overrides": param_overrides,
            }
        )
        
        # Build circuit via domain loader
        circuit = loader.build_circuit(
            template_id,
            parameters=param_overrides,
            custom_name=custom_name,
        )
        
        return circuit
    
    def _to_response(
        self,
        circuit: Circuit,
        request: GenerateFromTemplateRequest,
        session_id: str
    ) -> CircuitResponse:
        """Convert Circuit entity to response DTO with full metadata.
        
        Args:
            circuit: Generated circuit entity
            request: Original request
            session_id: Generation session ID
            
        Returns:
            CircuitResponse DTO
        """
        now = datetime.now()
        
        # Extract tags from circuit entity
        tags = list(circuit.tags) if hasattr(circuit, 'tags') and circuit.tags else []
        if not tags:
            # Generate default tags from topology
            tags = self._generate_default_tags(circuit, request)
        
        # Build comprehensive metadata
        metadata = {
            "template_id": request.template_id,
            "parameters": request.parameters,
            "topology_type": getattr(circuit, 'topology_type', 'unknown'),
            "category": getattr(circuit, 'category', 'amplifier'),
            "session_id": session_id,
            "generation_method": "TemplatesLoader",
            "domain_version": "2.0",
        }
        
        return CircuitResponse(
            circuit_id=circuit.id or str(uuid.uuid4()),
            name=circuit.name or request.circuit_name or "Unnamed Circuit",
            description=circuit.description or request.circuit_description or "Generated from template",
            tags=tags,
            created_at=now,
            updated_at=now,
            revision=1,
            created_by="GenerateCircuitUseCase",
            metadata=metadata,
            component_count=len(circuit.components),
            net_count=len(circuit.nets),
            port_count=len(circuit.ports),
            last_validation_status="valid",
            last_validation_at=now
        )
    
    @staticmethod
    def _generate_default_tags(
        circuit: Circuit,
        request: GenerateFromTemplateRequest
    ) -> List[str]:
        """Generate default tags based on circuit properties.
        
        Args:
            circuit: Circuit entity
            request: Generation request
            
        Returns:
            List of tags
        """
        tags = ["generated", "template"]
        
        # Add topology-based tags
        topology = getattr(circuit, 'topology_type', request.template_id.lower())
        if "bjt" in topology:
            tags.extend(["bjt", "transistor"])
        elif "mosfet" in topology or "fet" in topology:
            tags.extend(["mosfet", "fet"])
        elif "opamp" in topology:
            tags.extend(["opamp", "ic"])
        elif "power" in topology:
            tags.extend(["power", "amplifier"])
        
        # Add category tags
        category = getattr(circuit, 'category', '')
        if category:
            tags.append(category)
        
        return tags

    @staticmethod
    def _map_flat_params_to_components(
        template_dict: Dict[str, Any],
        flat_params: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        """Map flat parameters to per-component overrides based on parametric section.
        
        This method handles the translation from user-friendly flat parameters
        (e.g., {"vcc": 15, "gain": 20}) to domain-specific component overrides
        (e.g., {"VCC": {"voltage": 15}, "R1": {"resistance": 4700}}).
        
        Args:
            template_dict: Template definition with parametric section
            flat_params: User-provided flat parameters
            
        Returns:
            Component-level parameter overrides
        """
        result: Dict[str, Dict[str, Any]] = {}
        parametric = template_dict.get("parametric", {})
        components = template_dict.get("components", [])
        
        # --- Map power supply voltages (VCC, VDD, VEE) ---
        vcc_val = flat_params.get("vcc") or flat_params.get("vdd")
        vee_val = flat_params.get("vee")
        
        if vcc_val is not None:
            for comp in components:
                comp_id = comp.get("id", "")
                if comp_id in ("VCC", "VDD") and "voltage" in comp.get("parameters", {}):
                    result[comp_id] = {"voltage": float(vcc_val)}
        
        if vee_val is not None:
            for comp in components:
                comp_id = comp.get("id", "")
                if comp_id in ("VEE", "VSS") and "voltage" in comp.get("parameters", {}):
                    result[comp_id] = {"voltage": float(vee_val)}
        
        # --- Map component-specific overrides ---
        # Format 1: Direct component override {"R1": {"resistance": 4700}}
        # Format 2: Parametric lookup {"R1": 4700} → find param name from parametric section
        
        for key, val in flat_params.items():
            # Skip already processed global params
            if key in ("vcc", "vdd", "vee", "gain", "frequency"):
                continue
            
            if isinstance(val, dict):
                # Direct component override
                result[key] = val
            elif key in parametric:
                # key is component_id, val is single value → find parameter name
                comp_params = parametric[key]
                param_keys = [k for k in comp_params.keys() if k != "note"]
                
                if param_keys:
                    # Use first parameter (usually the main one)
                    result.setdefault(key, {})[param_keys[0]] = val
        
        return result
