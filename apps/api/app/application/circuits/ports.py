# .\thesis\electronic-chatbot\apps\api\app\application\circuits\ports.py
"""Application Ports - Định nghĩa interface cho infrastructure adapters.

Module này chịu trách nhiệm:
 1. Định nghĩa Protocol interfaces cho adapters
 2. Repository ports: lưu trữ circuit data
 3. Exporter ports: export circuit sang multi formats
 4. Validation ports: validate circuit rules

Nguyên tắc:
 - Protocol-based: abstraction, dễ mock cho tests
 - Domain-aware: hiểu Circuit/CircuitIR entities
 - Infrastructure-agnostic: không biết HTTP/DB details
 - Unidirectional dependency: application → infrastructure (qua ports)
"""

from __future__ import annotations

from typing import Protocol, Optional, Dict, Any, List, Union
from dataclasses import dataclass
from enum import Enum

# Import từ Domain
from app.domains.circuits.ir import CircuitIR
from app.domains.circuits.entities import Circuit, ComponentType
from app.domains.circuits.rules import (
    RuleViolation, ViolationSeverity, CircuitRulesEngine
)


# ===== CÁC PORT CHO KHO LƯU TRỮ (REPOSITORY) =====

class CircuitRepository(Protocol):
    """Port cho các thao tác lưu trữ dữ liệu mạch điện.
    
    Lưu ý: Repository lưu trữ dictionary IR (từ CircuitIRSerializer.to_dict()),
    không lưu trực tiếp thực thể Circuit. Điều này tách biệt domain khỏi định dạng lưu trữ.
    """
    
    async def save_ir(self, ir_dict: Dict[str, Any]) -> str:
        """
        Lưu IR của mạch vào bộ nhớ vĩnh viễn.
        
        Tham số:
            ir_dict: Dictionary CircuitIR đã được serialize (từ CircuitIRSerializer.to_dict())
                Phải bao gồm: meta, components, nets, ports, constraints, intent_snapshot
            
        Trả về:
            str: ID của mạch (được tạo mới hoặc cung cấp sẵn)
            
        Ngoại lệ:
            RepositoryError: Nếu thao tác lưu thất bại
        """
        ...
    
    async def get_ir(self, circuit_id: str, revision: Optional[int] = None) -> Dict[str, Any]:
        """
        Lấy IR của mạch từ bộ nhớ lưu trữ.
        
        Tham số:
            circuit_id: Mã định danh duy nhất của mạch
            revision: Phiên bản cụ thể (None nếu lấy bản mới nhất)
            
        Trả về:
            Dict[str, Any]: CircuitIR đã được serialize
            
        Ngoại lệ:
            CircuitNotFoundError: Nếu mạch không tồn tại
            RepositoryError: Nếu thao tác truy xuất thất bại
        """
        ...
    
    async def list_circuits(
        self, 
        user_id: Optional[str] = None, 
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Liệt kê danh sách các mạch có kèm bộ lọc.
        
        Tham số:
            user_id: Lọc theo người dùng/chủ sở hữu
            tags: Lọc theo thẻ
            limit: Số lượng kết quả tối đa
            offset: Vị trí bắt đầu (để phân trang)
            
        Trả về:
            Danh sách metadata của mạch (không bao gồm toàn bộ IR)
        """
        ...
    
    async def update_ir(self, circuit_id: str, ir_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Cập nhật mạch hiện có (tạo một phiên bản revision mới).
        
        Tham số:
            circuit_id: ID mạch cần cập nhật
            ir_dict: Dữ liệu mạch mới
            
        Trả về:
            Dict[str, Any]: Metadata của mạch sau khi cập nhật
            
        Ngoại lệ:
            CircuitNotFoundError: Nếu mạch không tồn tại
        """
        ...
    
    async def delete_circuit(self, circuit_id: str) -> bool:
        """
        Xóa mềm (soft-delete) một mạch điện.
        
        Tham số:
            circuit_id: ID mạch cần xóa
            
        Trả về:
            bool: Trạng thái thành công
            
        Ngoại lệ:
            CircuitNotFoundError: Nếu mạch không tồn tại
        """
        ...


class CircuitValidationRepository(Protocol):
    """Port để lưu trữ và truy xuất kết quả kiểm tra (validation)."""
    
    async def save_validation_result(
        self, 
        circuit_id: str, 
        validation_result: Dict[str, Any]
    ) -> str:
        """
        Lưu kết quả kiểm tra mạch.
        
        Tham số:
            circuit_id: ID của mạch
            validation_result: Các vi phạm quy tắc và tóm tắt
            
        Trả về:
            str: ID của kết quả kiểm tra
        """
        ...
    
    async def get_validation_history(
        self, 
        circuit_id: str, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Lấy lịch sử kiểm tra của một mạch điện.
        
        Tham số:
            circuit_id: ID của mạch
            limit: Số lượng bản ghi lịch sử tối đa
            
        Trả về:
            Danh sách các kết quả kiểm tra
        """
        ...


# ===== CÁC PORT CHO XUẤT DỮ LIỆU (EXPORTER) =====

class ExportFormat(Enum):
    """Các định dạng xuất dữ liệu được hỗ trợ."""
    KICAD = "kicad"           # Sơ đồ KiCad
    SPICE_NETLIST = "spice"   # Danh sách kết nối SPICE
    JSON = "json"             # Biểu diễn định dạng JSON
    PDF_SCHEMATIC = "pdf"     # Sơ đồ định dạng PDF
    PNG = "png"               # Ảnh PNG
    SVG = "svg"              # Ảnh vector SVG


class ExporterPort(Protocol):
    """Port để xuất mạch điện sang các định dạng khác nhau.
    
    Lưu ý: Các bộ xuất (Exporter) nên sử dụng CircuitIRSerializer.to_dict() 
    để lấy dữ liệu đã serialize trước khi chuyển đổi sang định dạng mục tiêu.
    """
    
    async def export(
        self, 
        ir: CircuitIR, 
        fmt: ExportFormat,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Xuất mạch điện sang định dạng chỉ định.
        
        Tham số:
            ir: Circuit IR cần xuất (dùng ir.circuit để truy cập thực thể Circuit)
            fmt: Định dạng xuất
            options: Các tùy chọn riêng cho từng định dạng
            
        Trả về:
            Dict[str, Any]: Kết quả xuất với dữ liệu đặc thù của định dạng
            Ví dụ: {"content": str, "filename": str, "mime_type": str}
            
        Ngoại lệ:
            ExportError: Nếu quá trình xuất thất bại
            UnsupportedFormatError: Nếu định dạng không được hỗ trợ
        """
        ...
    
    async def list_supported_formats(self) -> List[Dict[str, str]]:
        """
        Liệt kê tất cả các định dạng xuất được hỗ trợ.
        
        Trả về:
            Danh sách thông tin định dạng gồm tên, mô tả và phần mở rộng
        """
        ...


# ===== CÁC PORT CHO MÔ PHỎNG (SIMULATOR) =====

class SimulationType(Enum):
    """Các loại mô phỏng được hỗ trợ."""
    OPERATING_POINT = "op_point"      # Điểm làm việc DC
    TRANSIENT = "tran"                # Phân tích quá độ (miền thời gian)
    AC_ANALYSIS = "ac"                # Phân tích AC (miền tần số)
    DC_SWEEP = "dc"                   # Quét DC
    NOISE = "noise"                   # Phân tích nhiễu
    FOURIER = "fourier"              # Phân tích Fourier


@dataclass(frozen=True)
class SimulationConfig:
    """Cấu hình cho việc mô phỏng mạch điện."""
    simulation_type: SimulationType
    parameters: Dict[str, Any]  # Các tham số đặc thù cho từng loại mô phỏng
    timeout_seconds: int = 30
    max_iterations: int = 1000


@dataclass(frozen=True)
class SimulationResult:
    """Container chứa kết quả mô phỏng."""
    success: bool
    data: Dict[str, Any]           # Dữ liệu mô phỏng (dạng sóng, giá trị)
    metadata: Dict[str, Any]       # Siêu dữ liệu (thời gian chạy, thông tin solver)
    errors: List[str] = None       # Các lỗi hoặc cảnh báo nếu có
    raw_output: Optional[str] = None  # Đầu ra thô từ bộ mô phỏng


class SimulatorPort(Protocol):
    """Port cho các dịch vụ mô phỏng mạch điện."""
    
    async def simulate(
        self, 
        ir: CircuitIR, 
        config: SimulationConfig
    ) -> SimulationResult:
        """
        Mô phỏng mạch điện với cấu hình cho trước.
        
        Tham số:
            ir: Circuit IR cần mô phỏng
            config: Cấu hình mô phỏng
            
        Trả về:
            SimulationResult: Kết quả của quá trình mô phỏng
            
        Ngoại lệ:
            SimulationError: Nếu mô phỏng thất bại
            TimeoutError: Nếu quá thời gian mô phỏng
        """
        ...
    
    async def validate_simulation_config(
        self, 
        config: SimulationConfig
    ) -> List[str]:
        """
        Kiểm tra tính hợp lệ của cấu hình mô phỏng.
        
        Tham số:
            config: Cấu hình mô phỏng cần kiểm tra
            
        Trả về:
            List[str]: Danh sách các lỗi (trống nếu hợp lệ)
        """
        ...
    
    async def list_supported_simulations(self) -> Dict[SimulationType, List[str]]:
        """
        Liệt kê các loại mô phỏng được hỗ trợ và tham số đi kèm.
        
        Trả về:
            Dict bản đồ từ loại mô phỏng đến danh sách các tham số được hỗ trợ
        """
        ...


# ===== CÁC PORT CHO THƯ VIỆN LINH KIỆN (COMPONENT LIBRARY) =====

@dataclass(frozen=True)
class ComponentInfo:
    """Thông tin về một linh kiện từ thư viện.
    
    Lưu ý: Đây KHÔNG giống với thực thể Component trong domain.
    ComponentInfo dùng để tra cứu thư viện, Component dùng để thiết kế mạch.
    Dùng ComponentInfo để điền dữ liệu vào Component.parameters với ParameterValue.
    """
    model: str
    manufacturer: Optional[str]
    datasheet_url: Optional[str]
    parameters: Dict[str, Any]      # Tham số điện (sau này chuyển thành ParameterValue)
    package: Optional[str]          # Gói đóng gói vật lý
    spice_model: Optional[str]      # Tên model SPICE
    symbol: Optional[str]           # Tên ký hiệu sơ đồ
    footprint: Optional[str]        # Tên footprint PCB


class ComponentLibraryPort(Protocol):
    """Port cho các thao tác tra cứu thư viện linh kiện."""
    
    async def resolve_model(
        self, 
        component_type: ComponentType, 
        preferred_model: Optional[str] = None,
        constraints: Optional[Dict[str, Any]] = None
    ) -> ComponentInfo:
        """
        Tìm model linh kiện dựa trên loại và các ràng buộc.
        
        Tham số:
            component_type: Loại linh kiện (RESISTOR, CAPACITOR, v.v.)
            preferred_model: Tên model ưu tiên (nếu có)
            constraints: Ràng buộc về điện (giá trị, dung sai, v.v.)
            
        Trả về:
            ComponentInfo: Linh kiện phù hợp nhất
            
        Ngoại lệ:
            ComponentNotFoundError: Nếu không tìm thấy linh kiện phù hợp
            LibraryError: Nếu truy cập thư viện thất bại
        """
        ...
    
    async def search_components(
        self,
        query: str,
        component_type: Optional[ComponentType] = None,
        limit: int = 20
    ) -> List[ComponentInfo]:
        """
        Tìm kiếm linh kiện khớp với từ khóa.
        
        Tham số:
            query: Từ khóa tìm kiếm (model, nhà sản xuất, v.v.)
            component_type: Lọc theo loại linh kiện
            limit: Số lượng kết quả tối đa
            
        Trả về:
            Danh sách các linh kiện khớp
        """
        ...
    
    async def get_spice_model(self, model: str) -> str:
        """
        Lấy định nghĩa model SPICE cho linh kiện.
        
        Tham số:
            model: Tên model linh kiện
            
        Trả về:
            str: Định nghĩa model SPICE
            
        Ngoại lệ:
            ModelNotFoundError: Nếu không có model SPICE
        """
        ...
    
    async def validate_compatibility(
        self,
        components: List[ComponentInfo]
    ) -> List[Dict[str, Any]]:
        """
        Kiểm tra tính tương thích của linh kiện (ví dụ: định mức điện áp).
        
        Tham số:
            components: Danh sách linh kiện cần kiểm tra
            
        Trả về:
            Danh sách các vấn đề tương thích (trống nếu hoàn toàn tương thích)
        """
        ...


# ===== CÁC PORT CHO DỊCH VỤ TEMPLATE (MẪU MẠCH) =====

class TemplateServicePort(Protocol):
    """Port cho việc tạo và quản lý các mẫu mạch điện (templates).
    
    Hỗ trợ các mẫu từ template_builder.py:
    - Bộ khuếch đại BJT (CE, CC, CB)
    - Bộ khuếch đại OpAmp (đảo, không đảo, vi sai)
    - Các mẫu tham số tùy chỉnh
    """
    
    async def generate_from_template(
        self,
        template_name: str,
        parameters: Dict[str, Any]
    ) -> CircuitIR:
        """
        Tạo mạch từ mẫu với các tham số cho trước.
        
        Tham số:
            template_name: Mã định danh mẫu (vídụ: "bjt_ce", "opamp_inverting")
            parameters: Các tham số riêng của mẫu
                Với BJT: topology, gain, vcc, ic_target, beta, v.v.
                Với OpAmp: topology, gain, r1, r2, opamp_model, v.v.
            
        Trả về:
            CircuitIR: Mạch được tạo ra từ template_builder
            
        Ngoại lệ:
            TemplateNotFoundError: Nếu mẫu không tồn tại
            ParameterError: Nếu tham số không hợp lệ
        """
        ...
    
    async def list_templates(
        self,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Liệt kê các mẫu mạch có sẵn.
        
        Tham số:
            category: Lọc theo danh mục ("amplifier", "filter", "oscillator", v.v.)
            
        Trả về:
            Danh sách metadata của mẫu, mỗi mục gồm:
            {
                "name": tên mẫu,
                "description": mô tả,
                "category": danh mục,
                "parameters_schema": Dict,  # JSON schema cho các tham số
                "supported_topologies": List[str]  # ví dụ: ["CE", "CC", "CB"]
            }
        """
        ...
    
    async def save_template(
        self,
        ir: CircuitIR,
        name: str,
        description: str,
        tags: List[str],
        parameters_schema: Dict[str, Any]
    ) -> str:
        """
        Lưu một mạch điện thành mẫu có thể tái sử dụng.
        
        Tham số:
            ir: Mạch cần lưu thành mẫu
            name: Tên mẫu
            description: Mô tả mẫu
            tags: Thẻ phân loại
            parameters_schema: JSON schema cho các tham số
            
        Trả về:
            str: ID của mẫu
        """
        ...


# ===== CÁC PORT CHO DỊCH VỤ KIỂM TRA (VALIDATION) =====

class ValidationServicePort(Protocol):
    """Port cho các dịch vụ kiểm tra mạch điện."""
    
    async def validate_circuit(
        self,
        ir: CircuitIR,
        rule_set: Optional[str] = "default"
    ) -> Dict[str, Any]:
        """
        Kiểm tra mạch dựa trên bộ quy tắc bằng CircuitRulesEngine.
        
        Tham số:
            ir: Mạch cần kiểm tra
            rule_set: Tên bộ quy tắc ("default", "strict", "relaxed")
            
        Trả về:
            Dict với cấu trúc:
            {
                "is_valid": bool,
                "summary": {"total": tổng, "errors": lỗi, "warnings": cảnh báo, "info": thông tin},
                "violations": List[Dict] # RuleViolation.to_dict() đã serialize
            }
        """
        ...
    
    async def suggest_fixes(
        self,
        ir: CircuitIR,
        violations: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Gợi ý cách khắc phục cho các vi phạm khi kiểm tra.
        
        Tham số:
            ir: Mạch có vi phạm
            violations: Danh sách các vi phạm từ validate_circuit()
            
        Trả về:
            Danh sách các gợi ý sửa lỗi kèm mô tả
        """
        ...
    
    async def get_rule_sets(self) -> Dict[str, Dict[str, Any]]:
        """
        Lấy các bộ quy tắc hiện có và mô tả của chúng.
        
        Trả về:
            Dict bản đồ từ tên bộ quy tắc đến metadata của chúng
        """
        ...


# ===== CÁC LỚP LỖI (ERROR CLASSES) =====

class PortError(Exception):
    """Ngoại lệ cơ sở cho các lỗi liên quan đến Port."""
    pass


class RepositoryError(PortError):
    """Thao tác tại Repository thất bại."""
    pass


class CircuitNotFoundError(RepositoryError):
    """Không tìm thấy mạch trong kho lưu trữ."""
    pass


class ExportError(PortError):
    """Thao tác xuất dữ liệu thất bại."""
    pass


class UnsupportedFormatError(ExportError):
    """Định dạng xuất yêu cầu không được hỗ trợ."""
    pass


class SimulationError(PortError):
    """Thao tác mô phỏng thất bại."""
    pass


class ComponentNotFoundError(PortError):
    """Không tìm thấy linh kiện trong thư viện."""
    pass


class LibraryError(PortError):
    """Truy cập thư viện linh kiện thất bại."""
    pass


class TemplateNotFoundError(PortError):
    """Mẫu mạch không tồn tại."""
    pass


class ParameterError(PortError):
    """Tham số mẫu mạch không hợp lệ."""
    pass


class ValidationError(PortError):
    """Thao tác kiểm tra (validation) thất bại."""
    pass


# ===== ALIAS CHO KIỂU DỮ LIỆU (TYPE ALIASES) =====

# Dùng cho các container Dependency Injection
CircuitRepositoryPort = CircuitRepository
ExporterPort = ExporterPort
SimulatorPort = SimulatorPort
ComponentLibraryPort = ComponentLibraryPort
TemplateServicePort = TemplateServicePort
ValidationServicePort = ValidationServicePort