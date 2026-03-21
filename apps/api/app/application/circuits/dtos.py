# .\thesis\electronic-chatbot\apps\api\app\application\circuits\dtos.py
"""Data Transfer Objects (DTOs) cho Application Layer.

Module này chịu trách nhiệm:
 1. Định nghĩa request DTOs: nhận input từ HTTP/CLI
 2. Định nghĩa response DTOs: trả output ra HTTP/API
 3. Định nghĩa internal DTOs: truyền dữ liệu giữa use cases
 4. Validation: tất cả DTOs phải valid trước khi dùng

Nguyên tắc:
 - Adapter pattern: tứ layer application, tách biệt domain entities
 - Pydantic: automatic validation, serialization, JSON conversion
 - Immutable: frozen dataclass, không được mutate sau tạo

In/Out:
 - In: user input (HTTP request JSON) → Request DTO
 - Out: domain result → Response DTO → API JSON response
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field, validator
from pydantic.dataclasses import dataclass
from dataclasses import field  # Keep for other dataclasses
from datetime import datetime
from enum import Enum
import re

from app.domains.circuits.entities import ComponentType, PortDirection


# ===== VALIDATION HELPERS =====

class ValidationError(ValueError):
    """Base exception for DTO validation errors."""
    
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


def validate_non_empty_string(value: str, field_name: str) -> str:
    """Validate string is not empty."""
    if not value or not value.strip():
        raise ValidationError(field_name, "Không được để trống")
    return value.strip()


def validate_id_format(value: str, field_name: str) -> str:
    """Validate ID format (alphanumeric, dash, underscore)."""
    if not re.match(r'^[a-zA-Z0-9_\-]+$', value):
        raise ValidationError(
            field_name, 
            "Chỉ được chứa chữ cái, số, gạch dưới và gạch ngang"
        )
    return value


def validate_range(
    value: float, 
    field_name: str, 
    min_val: Optional[float] = None,
    max_val: Optional[float] = None
) -> float:
    """Validate numeric value is within range."""
    if min_val is not None and value < min_val:
        raise ValidationError(field_name, f"Phải >= {min_val}")
    if max_val is not None and value > max_val:
        raise ValidationError(field_name, f"Phải <= {max_val}")
    return value


# ===== PAGINATION DTOs =====

@dataclass
class PaginationRequest:
    """Request DTO for pagination."""
    page: int = 1
    page_size: int = 20
    sort_by: Optional[str] = None
    sort_order: str = "desc"  # "asc" or "desc"
    
    def __post_init__(self):
        self.page = max(1, self.page)
        self.page_size = max(1, min(self.page_size, 100))  # Cap at 100
        if self.sort_order not in ["asc", "desc"]:
            raise ValidationError("sort_order", "Phải là 'asc' hoặc 'desc'")


@dataclass
class PaginationResponse:
    """Response DTO for paginated results."""
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
    
    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages
    
    @property
    def has_prev(self) -> bool:
        return self.page > 1


# ===== CIRCUIT CRUD DTOs =====

@dataclass
class CreateCircuitRequest:
    """Request DTO để tạo circuit mới."""
    name: str
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    circuit_data: Optional[Dict[str, Any]] = None  # Raw circuit JSON (optional)
    template_id: Optional[str] = None  # Template để clone (optional)
    template_params: Optional[Dict[str, Any]] = None  # Tham số template
    
    def __post_init__(self):
        self.name = validate_non_empty_string(self.name, "name")
        if len(self.name) > 100:
            raise ValidationError("name", "Tên không được quá 100 ký tự")
        
        if self.description and len(self.description) > 1000:
            raise ValidationError("description", "Mô tả không được quá 1000 ký tự")
        
        # Validate tags
        for i, tag in enumerate(self.tags):
            if not re.match(r'^[a-zA-Z0-9\-_]+$', tag):
                raise ValidationError(f"tags[{i}]", "Tag chỉ được chứa chữ cái, số, gạch ngang, gạch dưới")
            if len(tag) > 50:
                raise ValidationError(f"tags[{i}]", "Tag không được quá 50 ký tự")


@dataclass
class UpdateCircuitRequest:
    """Request DTO để cập nhật circuit."""
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    circuit_data: Optional[Dict[str, Any]] = None
    revision_notes: Optional[str] = None
    
    def __post_init__(self):
        if self.name is not None:
            self.name = validate_non_empty_string(self.name, "name")
            if len(self.name) > 100:
                raise ValidationError("name", "Tên không được quá 100 ký tự")
        
        if self.description is not None and len(self.description) > 1000:
            raise ValidationError("description", "Mô tả không được quá 1000 ký tự")
        
        if self.revision_notes and len(self.revision_notes) > 500:
            raise ValidationError("revision_notes", "Ghi chú không được quá 500 ký tự")


@dataclass
class CircuitFilter:
    """Filter DTO cho danh sách circuits."""
    user_id: Optional[str] = None
    tags: Optional[List[str]] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    search_text: Optional[str] = None  # Search in name and description
    
    def __post_init__(self):
        if self.search_text and len(self.search_text.strip()) > 100:
            raise ValidationError("search_text", "Từ khóa tìm kiếm không được quá 100 ký tự")



class CircuitResponse(BaseModel):
    """Response DTO cho circuit."""
    circuit_id: str
    name: str
    description: Optional[str]
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    revision: int
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Circuit statistics
    component_count: int = 0
    net_count: int = 0
    port_count: int = 0
    
    # Validation status
    last_validation_status: Optional[str] = None  # "valid", "warning", "error"
    last_validation_at: Optional[datetime] = None
    
    @classmethod
    def from_ir_dict(cls, ir_dict: Dict[str, Any], user_id: Optional[str] = None) -> "CircuitResponse":
        """Tạo từ CircuitIR dictionary."""
        meta = ir_dict.get("meta", {})
        now = datetime.utcnow()
        return cls(
            circuit_id=meta.get("circuit_id", "unknown"),
            name=meta.get("circuit_name", "Unnamed"),
            description=None,  # Có thể lấy từ intent_snapshot
            tags=meta.get("tags", []),
            created_at=datetime.fromisoformat(meta.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(meta.get("created_at", datetime.utcnow().isoformat())),
            revision=meta.get("revision", 1),
            created_by=user_id,
            metadata={"schema_version": meta.get("schema_version")},
            component_count=len(ir_dict.get("components", [])),
            net_count=len(ir_dict.get("nets", [])),
            port_count=len(ir_dict.get("ports", []))
        )


@dataclass
class CircuitDetailResponse:
    """Response DTO chi tiết cho circuit (bao gồm cả data)."""
    circuit: CircuitResponse
    circuit_data: Dict[str, Any]  # Full IR data
    intent_snapshot: Optional[Dict[str, Any]] = None


# ===== EXPORT DTOs =====

class ExportFormat(str, Enum):
    """Export format enum."""
    KICAD = "kicad"
    KICAD_PCB = "kicad_pcb"
    SPICE = "spice"
    JSON = "json"
    PDF = "pdf"
    PNG = "png"
    SVG = "svg"


@dataclass
class ExportCircuitRequest:
    """Request DTO để export circuit."""
    circuit_id: str
    format: ExportFormat
    options: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.circuit_id = validate_id_format(self.circuit_id, "circuit_id")
        
        # Validate format-specific options
        if self.format == ExportFormat.PDF:
            page_size = self.options.get("page_size", "A4")
            if page_size not in ["A4", "A3", "Letter", "Legal"]:
                raise ValidationError("options.page_size", "Kích thước trang không hợp lệ")
        
        elif self.format == ExportFormat.PNG:
            dpi = self.options.get("dpi", 300)
            if dpi < 72 or dpi > 1200:
                raise ValidationError("options.dpi", "DPI phải trong khoảng 72-1200")



class ExportCircuitResponse(BaseModel):
    """Response DTO cho export."""
    circuit_id: str
    format: ExportFormat
    file_path: Optional[str] = None  # Path to exported file
    download_url: Optional[str] = None  # URL để download file
    file_content: Optional[bytes] = None  # Raw file content (cho small files)
    file_size: Optional[int] = None  # Kích thước file (bytes)
    export_time: datetime = Field(default_factory=datetime.utcnow)
    
    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True


# ===== SIMULATION DTOs =====

class SimulationType(str, Enum):
    """Simulation type enum."""
    OP_POINT = "op_point"
    TRANSIENT = "transient"
    AC_ANALYSIS = "ac"
    DC_SWEEP = "dc_sweep"
    NOISE = "noise"
    FOURIER = "fourier"


@dataclass
class SimulationParameter:
    """Single simulation parameter."""
    name: str
    value: Union[float, str, bool]
    unit: Optional[str] = None
    
    def __post_init__(self):
        self.name = validate_non_empty_string(self.name, "name")
        
        # Validate numeric values
        if isinstance(self.value, (int, float)):
            if self.value < 0 and self.name in ["stop_time", "start_time", "step_time"]:
                raise ValidationError("value", "Thời gian không được âm")


@dataclass
class SimulationConfig:
    """Simulation configuration DTO."""
    simulation_type: SimulationType
    parameters: List[SimulationParameter] = field(default_factory=list)
    
    # Advanced options
    solver: str = "default"
    temperature: float = 27.0  # Celsius
    max_iterations: int = 1000
    timeout_seconds: int = 30
    
    def __post_init__(self):
        validate_range(self.temperature, "temperature", -273.15, 1000)
        validate_range(self.max_iterations, "max_iterations", min_val=1)
        validate_range(self.timeout_seconds, "timeout_seconds", min_val=1, max_val=300)
        
        # Validate parameters based on simulation type
        self._validate_parameters()
    
    def _validate_parameters(self):
        """Validate parameters for specific simulation type."""
        param_names = {p.name for p in self.parameters}
        
        if self.simulation_type == SimulationType.TRANSIENT:
            required = {"stop_time"}
            if not required.issubset(param_names):
                raise ValidationError(
                    "parameters", 
                    f"Transient simulation cần các tham số: {required}"
                )
        
        elif self.simulation_type == SimulationType.AC_ANALYSIS:
            required = {"start_freq", "stop_freq"}
            if not required.issubset(param_names):
                raise ValidationError(
                    "parameters", 
                    f"AC analysis cần các tham số: {required}"
                )
        
        elif self.simulation_type == SimulationType.DC_SWEEP:
            required = {"source", "start", "stop"}
            if not required.issubset(param_names):
                raise ValidationError(
                    "parameters", 
                    f"DC sweep cần các tham số: {required}"
                )


@dataclass
class SimulationRequest:
    """Request DTO để chạy simulation."""
    circuit_id: str
    config: SimulationConfig
    probes: List[str] = field(default_factory=list)  # Các node cần monitor
    
    def __post_init__(self):
        self.circuit_id = validate_id_format(self.circuit_id, "circuit_id")
        
        # Validate probe names
        for i, probe in enumerate(self.probes):
            if not re.match(r'^[a-zA-Z0-9_\-\.]+$', probe):
                raise ValidationError(f"probes[{i}]", "Tên probe không hợp lệ")


@dataclass
class SimulationResult:
    """Single simulation result data point."""
    value: Union[float, complex, List[float]]
    time: Optional[float] = None  # Thời gian (transient)
    frequency: Optional[float] = None  # Tần số (AC)
    unit: Optional[str] = None


@dataclass
class SimulationResponse:
    """Response DTO cho simulation."""
    simulation_id: str
    circuit_id: str
    config: SimulationConfig
    success: bool
    results: Dict[str, List[SimulationResult]]  # probe_name -> results
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Performance metrics
    execution_time_ms: float = 0.0
    memory_usage_mb: float = 0.0
    convergence_iterations: Optional[int] = None
    
    # Raw data (optional, cho advanced use)
    raw_data: Optional[Dict[str, Any]] = None


# ===== COMPONENT LIBRARY DTOs =====

@dataclass
class ComponentSearchRequest:
    """Request DTO để tìm kiếm linh kiện."""
    query: str
    component_type: Optional[ComponentType] = None
    manufacturer: Optional[str] = None
    value_range: Optional[Dict[str, float]] = None  # {"min": 0, "max": 100}
    tolerance_max: Optional[float] = None  # Max tolerance (%)
    package_type: Optional[str] = None
    limit: int = 20
    offset: int = 0
    
    def __post_init__(self):
        self.query = validate_non_empty_string(self.query, "query")
        validate_range(self.limit, "limit", min_val=1, max_val=100)
        validate_range(self.offset, "offset", min_val=0)
        
        if self.tolerance_max is not None:
            validate_range(self.tolerance_max, "tolerance_max", min_val=0, max_val=100)


@dataclass
class ComponentParameter:
    """Component parameter DTO."""
    name: str
    value: Union[float, str]
    unit: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    typical_value: Optional[float] = None


@dataclass
class ComponentResponse:
    """Response DTO cho component information."""
    model: str
    manufacturer: str
    component_type: ComponentType
    description: str
    
    # Electrical parameters
    parameters: List[ComponentParameter]
    
    # Physical characteristics
    package: Optional[str] = None
    footprint: Optional[str] = None
    symbol: Optional[str] = None
    
    # Model information
    spice_model: Optional[str] = None
    vendor_part_number: Optional[str] = None
    
    # References
    datasheet_url: Optional[str] = None
    vendor_url: Optional[str] = None
    price_range: Optional[Dict[str, float]] = None  # {"min": 0.1, "max": 1.0}
    
    # Availability
    in_stock: bool = True
    lead_time_days: Optional[int] = None


@dataclass
class ComponentSelectionRequest:
    """Request DTO để chọn linh kiện tự động."""
    component_type: ComponentType
    constraints: Dict[str, Any]  # {"resistance": 1000, "tolerance": 5}
    preferred_manufacturer: Optional[str] = None
    budget_constraint: Optional[float] = None  # Max price
    
    def __post_init__(self):
        # Validate constraints based on component type
        if self.component_type == ComponentType.RESISTOR:
            if "resistance" not in self.constraints:
                raise ValidationError("constraints", "Resistor cần tham số 'resistance'")
            validate_range(
                self.constraints["resistance"], 
                "constraints.resistance", 
                min_val=0
            )
        
        elif self.component_type == ComponentType.CAPACITOR:
            if "capacitance" not in self.constraints:
                raise ValidationError("constraints", "Capacitor cần tham số 'capacitance'")
            validate_range(
                self.constraints["capacitance"], 
                "constraints.capacitance", 
                min_val=0
            )


# ===== TEMPLATE DTOs =====

@dataclass
class TemplateParameter:
    """Template parameter DTO."""
    name: str
    type: str  # "number", "string", "boolean", "enum"
    description: Optional[str] = None
    default_value: Optional[Union[float, str, bool]] = None
    constraints: Optional[Dict[str, Any]] = None  # {"min": 0, "max": 100, "options": [...]}
    required: bool = True
    
    def __post_init__(self):
        self.name = validate_non_empty_string(self.name, "name")
        if self.type not in ["number", "string", "boolean", "enum"]:
            raise ValidationError("type", "Loại tham số không hợp lệ")


@dataclass
class TemplateInfo:
    """Template information DTO."""
    template_id: str
    name: str
    description: str
    category: str  # "amplifier", "filter", "power_supply", "oscillator"
    tags: List[str]
    parameters: List[TemplateParameter]
    
    # Statistics
    usage_count: int = 0
    avg_rating: Optional[float] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    is_public: bool = True


class GenerateFromTemplateRequest(BaseModel):
    """Request DTO để generate circuit từ template."""
    template_id: str
    parameters: Dict[str, Any]
    circuit_name: Optional[str] = None
    circuit_description: Optional[str] = None
    
    @validator('template_id')
    def validate_template_id(cls, v):
        try:
            return validate_id_format(v, "template_id")
        except ValidationError as e:
            raise ValueError(e.message)
    
    @validator('circuit_name')
    def validate_circuit_name(cls, v):
        if v:
            try:
                v = validate_non_empty_string(v, "circuit_name")
                if len(v) > 100:
                    raise ValueError("Tên không được quá 100 ký tự")
            except ValidationError as e:
                raise ValueError(e.message)
        return v
    
    class Config:
        json_schema_extra = {
            "example": {
                "template_id": "bjt_common_emitter",
                "parameters": {"gain": 10, "vcc": 12},
                "circuit_name": "Test CE Amplifier",
                "circuit_description": "Common Emitter amplifier for testing"
            }
        }


class GenerateFromPromptRequest(BaseModel):
    """Request DTO to generate circuit from natural language prompt."""
    prompt: str = Field(..., description="Natural language description of desired circuit")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Explicit parameters")
    circuit_name: Optional[str] = None
    circuit_description: Optional[str] = None
    
    @validator('prompt')
    def validate_prompt(cls, v):
        if not v or not v.strip():
            raise ValueError("Prompt cannot be empty")
        if len(v) > 1000:
            raise ValueError("Prompt too long (max 1000 characters)")
        return v.strip()
    
    class Config:
        json_schema_extra = {
            "example": {
                "prompt": "Create a BJT common emitter amplifier with gain of 10 and VCC=12V",
                "parameters": {},
                "circuit_name": "My CE Amplifier"
            }
        }


class ClarifyingQuestionDTO(BaseModel):
    """DTO for a clarifying question."""
    field: str = Field(..., description="Parameter name")
    question: str = Field(..., description="User-friendly question")
    suggestions: List[str] = Field(default_factory=list, description="Suggested values")
    required: bool = Field(True, description="Is this parameter required?")


class PromptAnalysisResponse(BaseModel):
    """Response DTO for prompt analysis."""
    clarity: str = Field(..., description="clear, ambiguous, or invalid")
    template_id: Optional[str] = Field(None, description="Detected template ID")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Extracted parameters")
    questions: List[ClarifyingQuestionDTO] = Field(default_factory=list, description="Clarifying questions if ambiguous")
    confidence: float = Field(0.0, description="Confidence in template detection (0.0-1.0)")
    message: Optional[str] = Field(None, description="User-friendly message")


@dataclass
class CreateTemplateRequest:
    """Request DTO để tạo template mới."""
    name: str
    description: str
    category: str
    tags: List[str]
    parameters_schema: List[TemplateParameter]
    example_parameters: Dict[str, Any]
    circuit_data: Dict[str, Any]  # Circuit IR để dùng làm template
    is_public: bool = True
    
    def __post_init__(self):
        self.name = validate_non_empty_string(self.name, "name")
        if len(self.name) > 100:
            raise ValidationError("name", "Tên không được quá 100 ký tự")
        
        self.description = validate_non_empty_string(self.description, "description")
        if len(self.description) > 500:
            raise ValidationError("description", "Mô tả không được quá 500 ký tự")


# ===== VALIDATION DTOs =====

class ViolationSeverity(str, Enum):
    """Violation severity enum."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ViolationDetail:
    """Single violation detail."""
    rule_name: str
    message: str
    severity: ViolationSeverity
    component_id: Optional[str] = None
    net_name: Optional[str] = None
    port_name: Optional[str] = None
    constraint_name: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.message = validate_non_empty_string(self.message, "message")
        self.rule_name = validate_non_empty_string(self.rule_name, "rule_name")


@dataclass
class ValidationRequest:
    """Request DTO để validate circuit."""
    circuit_id: Optional[str] = None
    circuit_data: Optional[Dict[str, Any]] = None  # Raw circuit data (nếu không có ID)
    rule_set: str = "default"  # "default", "strict", "relaxed"
    check_fixes: bool = False  # Có đề xuất sửa lỗi không
    
    def __post_init__(self):
        if not self.circuit_id and not self.circuit_data:
            raise ValidationError("", "Cần cung cấp circuit_id hoặc circuit_data")
        
        if self.circuit_id:
            self.circuit_id = validate_id_format(self.circuit_id, "circuit_id")


@dataclass
class FixSuggestion:
    """Suggestion for fixing a violation."""
    violation_id: str  # Reference to violation
    description: str
    action: str  # "add_component", "modify_parameter", "change_connection"
    parameters: Dict[str, Any]  # Action-specific parameters
    estimated_impact: str = "low"  # "low", "medium", "high"
    
    def __post_init__(self):
        self.description = validate_non_empty_string(self.description, "description")
        self.action = validate_non_empty_string(self.action, "action")


@dataclass
class ValidationResponse:
    """Response DTO cho validation."""
    validation_id: str
    circuit_id: Optional[str]
    timestamp: datetime
    rule_set: str
    
    # Results
    is_valid: bool  # True nếu không có ERROR
    violations: List[ViolationDetail]
    fix_suggestions: List[FixSuggestion] = field(default_factory=list)
    
    # Statistics
    summary: Dict[str, int] = field(default_factory=dict)  # {"errors": 0, "warnings": 2, "info": 1}
    execution_time_ms: float = 0.0
    
    @property
    def error_count(self) -> int:
        return len([v for v in self.violations if v.severity == ViolationSeverity.ERROR])
    
    @property
    def warning_count(self) -> int:
        return len([v for v in self.violations if v.severity == ViolationSeverity.WARNING])


# ===== ANALYSIS DTOs =====

@dataclass
class CircuitAnalysisRequest:
    """Request DTO cho các loại phân tích circuit."""
    circuit_id: str
    analysis_type: str  # "dc_operating_point", "gain_analysis", "frequency_response"
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.circuit_id = validate_id_format(self.circuit_id, "circuit_id")
        self.analysis_type = validate_non_empty_string(self.analysis_type, "analysis_type")


@dataclass
class AnalysisResult:
    """Generic analysis result."""
    analysis_id: str
    circuit_id: str
    analysis_type: str
    timestamp: datetime
    
    results: Dict[str, Any]  # Analysis-specific results
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


# ===== BATCH OPERATION DTOs =====

@dataclass
class BatchOperationRequest:
    """Request DTO cho batch operations."""
    operation: str  # "validate", "export", "simulate"
    circuit_ids: List[str]
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.circuit_ids:
            raise ValidationError("circuit_ids", "Danh sách circuit không được trống")
        
        if len(self.circuit_ids) > 100:
            raise ValidationError("circuit_ids", "Tối đa 100 circuits mỗi batch")
        
        for i, circuit_id in enumerate(self.circuit_ids):
            try:
                validate_id_format(circuit_id, f"circuit_ids[{i}]")
            except ValidationError as e:
                raise ValidationError(f"circuit_ids[{i}]", str(e))


@dataclass
class BatchOperationResult:
    """Single result in batch operation."""
    circuit_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


@dataclass
class BatchOperationResponse:
    """Response DTO cho batch operation."""
    operation_id: str
    operation: str
    total_count: int
    success_count: int
    failed_count: int
    results: List[BatchOperationResult]
    total_time_ms: float = 0.0


# ===== ERROR RESPONSE DTOs =====

@dataclass
class ErrorDetail:
    """Error detail for API responses."""
    code: str
    message: str
    field: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        self.code = validate_non_empty_string(self.code, "code")
        self.message = validate_non_empty_string(self.message, "message")


@dataclass
class ErrorResponse:
    """Standard error response DTO."""
    error: ErrorDetail
    timestamp: datetime = field(default_factory=datetime.utcnow)
    request_id: Optional[str] = None
    
    @classmethod
    def from_validation_error(cls, validation_error: ValidationError, request_id: Optional[str] = None) -> ErrorResponse:
        """Tạo từ ValidationError."""
        return cls(
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message=str(validation_error),
                field=validation_error.field
            ),
            request_id=request_id
        )
    
    @classmethod
    def from_exception(cls, exception: Exception, request_id: Optional[str] = None) -> ErrorResponse:
        """Tạo từ generic exception."""
        return cls(
            error=ErrorDetail(
                code="INTERNAL_ERROR",
                message=str(exception)
            ),
            request_id=request_id
        )


# ===== WEBHOOK/NOTIFICATION DTOs =====

@dataclass
class WebhookEvent:
    """Webhook event DTO."""
    event_type: str  # "circuit.created", "simulation.completed", "validation.failed"
    event_id: str
    timestamp: datetime
    data: Dict[str, Any]
    circuit_id: Optional[str] = None
    user_id: Optional[str] = None
    
    def __post_init__(self):
        self.event_type = validate_non_empty_string(self.event_type, "event_type")
        self.event_id = validate_non_empty_string(self.event_id, "event_id")


@dataclass
class Notification:
    """Notification DTO."""
    notification_id: str
    user_id: str
    title: str
    message: str
    type: str = "info"  # "info", "warning", "error", "success"
    data: Dict[str, Any] = field(default_factory=dict)
    read: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def __post_init__(self):
        self.title = validate_non_empty_string(self.title, "title")
        self.message = validate_non_empty_string(self.message, "message")
        if self.type not in ["info", "warning", "error", "success"]:
            raise ValidationError("type", "Loại notification không hợp lệ")


# ===== TYPE ALIASES =====

# For import convenience
CircuitCreateDTO = CreateCircuitRequest
CircuitUpdateDTO = UpdateCircuitRequest
CircuitListDTO = CircuitFilter
CircuitGetDTO = CircuitResponse
CircuitDetailDTO = CircuitDetailResponse

ExportRequestDTO = ExportCircuitRequest
ExportResponseDTO = ExportCircuitResponse

SimulationRequestDTO = SimulationRequest
SimulationResponseDTO = SimulationResponse

ComponentSearchDTO = ComponentSearchRequest
ComponentSelectionDTO = ComponentSelectionRequest
ComponentInfoDTO = ComponentResponse

TemplateInfoDTO = TemplateInfo
TemplateGenerateDTO = GenerateFromTemplateRequest
TemplateCreateDTO = CreateTemplateRequest

ValidationRequestDTO = ValidationRequest
ValidationResponseDTO = ValidationResponse

BatchRequestDTO = BatchOperationRequest
BatchResponseDTO = BatchOperationResponse

ErrorDTO = ErrorResponse