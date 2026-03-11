# Hệ Thống Tự Động Sắp Xếp Vị Trí Linh Kiện

## Tổng Quan

Hệ thống tự động sắp xếp vị trí các linh kiện trong sơ đồ mạch điện theo các quy tắc đã định nghĩa sẵn, giúp tạo layout nhất quán và dễ đọc.

## Quy Tắc Sắp Xếp

### 1. Nguồn Cấp (Power)
- **Vị trí**: Trên cùng, căn giữa (y = 0, x = center)
- **Các linh kiện**: VCC, VDD, hoặc ComponentType.VOLTAGE_SOURCE
- **Nhóm**: `group = "power"`

### 2. Ground (GND)
- **Vị trí**: Dưới cùng, căn giữa (y = max, x = center)
- **Các linh kiện**: GND hoặc ComponentType.GROUND
- **Nhóm**: `group = "power"`

### 3. Linh Kiện Khác
- **Vị trí**: Sắp xếp theo grid từ trái sang phải, từ trên xuống dưới
- **Khoảng cách**: 
  - Ngang (spacing_x): 20mm mặc định
  - Dọc (spacing_y): 20mm mặc định
- **Nhóm**: Giữ nguyên group hiện có (amplifier, bias, coupling, bypass...)

## Cách Sử Dụng

### Sử Dụng Trực Tiếp Với Template

```python
from app.domains.circuits.topology_templates import (
    TopologyTemplateRegistry,
    auto_arrange_positions
)

# Lấy template
template = TopologyTemplateRegistry.get("bjt_common_emitter")

# Các linh kiện đã được tự động sắp xếp khi load template
components = template["components"]

# Xem vị trí các linh kiện
for comp in components:
    print(f"{comp['id']}: x={comp['position']['x']}, y={comp['position']['y']}")
```

### Sắp Xếp Lại Với Khoảng Cách Tùy Chỉnh

```python
from app.domains.circuits.topology_templates import auto_arrange_positions

# Sắp xếp với khoảng cách tùy chỉnh
components = [...]  # Danh sách linh kiện
auto_arrange_positions(components, spacing_x=30, spacing_y=25)
```

## Ví Dụ Kết Quả

### BJT Common Emitter (9 linh kiện)

```
Nguồn:
  VCC: x=30.0, y=0 (trên cùng, center)

Linh kiện (4 cột x 2 hàng):
  Q1:  x=0,  y=40  (hàng 1, cột 1)
  RC:  x=20, y=40  (hàng 1, cột 2)
  RB:  x=40, y=40  (hàng 1, cột 3)
  RE:  x=60, y=40  (hàng 1, cột 4)
  CE:  x=0,  y=60  (hàng 2, cột 1)
  CIN: x=20, y=60  (hàng 2, cột 2)
  COUT:x=40, y=60  (hàng 2, cột 3)

GND:
  GND: x=30.0, y=100 (dưới cùng, center)
```

### Op-Amp Inverting (6 linh kiện)

```
Nguồn:
  VCC: x=20.0, y=0
  VEE: x=20.0, y=0

Linh kiện (2 cột x 1 hàng):
  U1:  x=0,  y=40
  RIN: x=20, y=40
  RF:  x=40, y=40

GND:
  GND: x=20.0, y=80
```

## Thuật Toán

### Bước 1: Phân Loại Linh Kiện
```python
for comp in components:
    if comp_type == VOLTAGE_SOURCE or "VCC/VDD" in comp_id:
        → power_components
    elif comp_type == GROUND or "GND" in comp_id:
        → ground_components
    else:
        → other_components
```

### Bước 2: Tính Grid Layout
```python
num_components = len(other_components)
cols = int(sqrt(num_components)) + 1  # Số cột
total_width = (cols - 1) * spacing_x
center_x = total_width / 2
```

### Bước 3: Đặt Vị Trí
```python
# Power ở trên
for comp in power_components:
    comp.position = (center_x, 0)

# Grid cho các linh kiện khác
for idx, comp in enumerate(other_components):
    row = idx // cols
    col = idx % cols
    comp.position = (col * spacing_x, 40 + row * spacing_y)

# GND ở dưới
for comp in ground_components:
    comp.position = (center_x, max_y + spacing_y)
```

## Mở Rộng

### 1. Tùy Chỉnh Quy Tắc
Để thêm quy tắc mới, chỉnh sửa hàm `auto_arrange_positions()` trong [topology_templates.py](../topology_templates.py):

```python
def auto_arrange_positions(components, spacing_x=20, spacing_y=20):
    # Thêm các quy tắc phân loại mới
    input_components = []  # Input ở bên trái
    output_components = []  # Output ở bên phải
    
    # Phân loại
    for comp in components:
        if "INPUT" in comp["id"]:
            input_components.append(comp)
        elif "OUTPUT" in comp["id"]:
            output_components.append(comp)
    
    # Đặt vị trí theo quy tắc mới
    # ...
```

### 2. Sử Dụng AI/ML (Tương Lai)
Khi có đủ dữ liệu sơ đồ mẫu, có thể training model ML:

```python
def ml_based_arrange_positions(components, model):
    """Dự đoán vị trí tối ưu dựa trên ML model"""
    # Extract features
    features = extract_features(components)
    
    # Predict positions
    positions = model.predict(features)
    
    # Apply positions
    for comp, pos in zip(components, positions):
        comp["position"] = {"x": pos[0], "y": pos[1]}
```

**Dữ liệu training**:
- Input: đặc trưng linh kiện (type, id, parameters, connections)
- Output: vị trí tối ưu (x, y)
- Dataset: Nhiều sơ đồ mạch được bố trí thủ công bởi chuyên gia

## Kiểm Tra

Chạy test suite để xác minh:

```bash
# Test chức năng cơ bản
python -m app.domains.circuits.test_topology_system

# Test chi tiết về auto-arrange
python -m app.domains.circuits.test_auto_arrange
```

## Tham Khảo

- [topology_templates.py](../topology_templates.py) - Implementation
- [test_topology_system.py](../test_topology_system.py) - Test suite
- [test_auto_arrange.py](../test_auto_arrange.py) - Test auto-arrange
