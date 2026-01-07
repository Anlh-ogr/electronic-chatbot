# entities.py - Domain Entities cho Intent-driven Circuit Synthesis System

File này là **trái tim** của Domain Layer trong hệ thống Circuit Synthesis – nơi định nghĩa **Source of Truth** của toàn bộ mạch điện.

**TUYỆT ĐỐI KHÔNG** chứa:
- Logic AI (reasoning, intent parsing, LLM calls)
- Logic rendering (KiCanvas, schematic drawing)
- Logic simulation (NgSpice netlist generation)
- UI / API / WebSocket logic
- Bất kỳ mutable state nào

Chỉ chứa **pure domain entities** với **invariants nghiêm ngặt**, đảm bảo mọi mạch được sinh ra đều **hợp lệ về cấu trúc** trước khi đi vào các layer khác.

## Mục tiêu thiết kế

1. **Immutable Source of Truth**  
   Toàn bộ entities dùng `@dataclass(frozen=True)` → không layer nào được phép sửa trực tiếp.

2. **Validation sớm & chặt**  
   Invariants được kiểm tra ngay trong `__post_init__` và `validate_basic()` → lỗi phát hiện sớm nhất có thể.

3. **IR ổn định cho AI**  
   AI chỉ thao tác qua các factory/service ở layer trên → không bao giờ phá kiểu dữ liệu.

4. **Chuẩn bị cho Rules Engine**  
   Các validation hiện tại là "hard-coded". Sau này sẽ chuyển sang rule engine động (tuần 2+).

## Cấu trúc file

### 1. Enums
- `ComponentType`: Danh sách linh kiện hỗ trợ (cố định, không cho user thêm).
- `PortDirection`: Hướng port chuẩn hóa (INPUT/OUTPUT/POWER/GROUND).

### 2. Value Objects
- `ParameterValue`: Bao bọc giá trị tham số (value + unit), chỉ chấp nhận `int/float/str`.
- `PinRef`: Tham chiếu chuẩn đến một chân linh kiện (component_id + pin_name).

### 3. Core Entities
- `Component`: Linh kiện vật lý (id, type, pins, parameters).
- `Net`: Dây nối điện giữa các chân.
- `Port`: Giao diện của mạch với thế giới bên ngoài.
- `Constraint`: Ý định kỹ thuật (supply_voltage, target_gain, ...).

### 4. Aggregate Root
- `Circuit`: Entity cao nhất, chứa tất cả components/nets/ports/constraints.
  - Có method `validate_basic()` kiểm tra tính toàn vẹn cấu trúc.
  - Có helper immutable copy: `with_component()`.

## Hướng dẫn sử dụng

### Tạo một mạch đơn giản (ví dụ trong test hoặc factory)

```python
from app.domains.circuits.entities import (
    ComponentType, ParameterValue, Component, PinRef, Net, Port, Circuit
)

# 1. Tạo components
r1 = Component(
    id="R1",
    type=ComponentType.RESISTOR,
    pins=("A", "B"),
    parameters={"resistance": ParameterValue(value=10000, unit="Ohm")}
)

vs = Component(
    id="VS1",
    type=ComponentType.VOLTAGE_SOURCE,
    pins=("POS", "NEG"),
    parameters={"voltage": ParameterValue(value=5, unit="V")}
)

gnd = Component(
    id="GND1",
    type=ComponentType.GROUND,
    pins=("G",)
)

# 2. Tạo nets
net_vcc = Net(
    name="VCC",
    connected_pins=(
        PinRef(component_id="VS1", pin_name="POS"),
        PinRef(component_id="R1", pin_name="A"),
    )
)

net_gnd = Net(
    name="GND",
    connected_pins=(
        PinRef(component_id="VS1", pin_name="NEG"),
        PinRef(component_id="R1", pin_name="B"),
        PinRef(component_id="GND1", pin_name="G"),
    )
)

# 3. Tạo ports
vin = Port(name="VIN", net_name="VCC", direction=None)
gnd_port = Port(name="GND", net_name="GND", direction=None)

# 4. Tạo Circuit
circuit = Circuit(
    name="Simple Voltage Divider",
    components={"R1": r1, "VS1": vs, "GND1": gnd},
    nets={"VCC": net_vcc, "GND": net_gnd},
    ports={"VIN": vin, "GND": gnd_port},
    constraints={}
)

# circuit giờ đã được validate tự động → hợp lệ về cấu trúc
```

### Thêm component mới (immutable way)
```python
new_cap = Component(
    id="C1",
    type=ComponentType.CAPACITOR,
    pins=("A", "B"),
    parameters={"capacitance": ParameterValue(value=1e-6, unit="F")}
)

updated_circuit = circuit.with_component(new_cap)
# circuit cũ vẫn giữ nguyên, updated_circuit là bản mới
```

## Debug & Common Errors
Lỗi thường gặp | Nguyên nhân | Cách fix
--- | --- | ---
`ValueError: ParameterValue.value không được None` | Truyền `None` vào ParameterValue | Luôn truyền giá trị hợp lệ (int/float/str)
`TypeError: ParameterValue.value chỉ chấp nhận int/float/str` | Truyền dict/list/function vào value | Chỉ dùng primitive types
`ValueError: Resistor R1 phải có tham số 'resistance'` | Thiếu parameter bắt buộc theo type | Thêm parameter đúng tên (xem validation trong **Component.post_init**)
`ValueError: Dây nối 'VCC' kết nối đến linh kiện không tồn tại 'R2'` | PinRef trỏ đến component chưa có trong dict | Đảm bảo tất cả component được thêm vào `components` dict trước
`ValueError: Port 'VIN' kết nối đến dây nối không tồn tại 'XYZ'` | Port trỏ đến net không tồn tại | Kiểm tra tên net_name khớp với key trong `nets`
`ValueError: Component ID không khớp: key 'R1' khác với component.id 'R2'` | Key trong dict không khớp với `component.id` | Luôn dùng `component.id` làm key

### Tip debug nhanh:
- Tạo circuit từng bước và để exception ném ra → lỗi sẽ chỉ rõ chỗ sai.
- Không cố "fix" bằng cách sửa trực tiếp object (vì frozen) → phải tạo mới.


## Nguyên tắc mở rộng (cho dev sau này)
1. Không thêm validation điện sâu ở đây
   - Ví dụ: kiểm tra gain, bias point, stability → thuộc Rules Engine (layer riêng).
2. Không thêm mutable methods
   - Chỉ được thêm immutable copy helpers kiểu `with_xxx()`.
3. Không thêm field liên quan đến rendering/simulation
   - position, symbol, footprint, spice_model → cấm tuyệt đối.
4. Muốn thêm component type mới
   - Thêm vào `ComponentType` enum.
   - Thêm validation parameter bắt buộc trong `Component.__post_init__` (tạm thời).
   - Sau này chuyển sang rule config.


## Tương lai (roadmap)