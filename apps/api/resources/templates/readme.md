# Template Index Structure - Cấu Trúc Phân Loại Mạch

## Tổng Quan

Thư mục templates chứa các file template JSON mô tả cấu trúc mạch điện tử và các file index để phân loại, quản lý metadata.

## Cấu Trúc Phân Loại Mới

### 1. **_index_bjt.json** - BJT Amplifiers
**Category:** `bjt_amplifier`  
**Mô tả:** Các mạch khuếch đại dùng BJT (Bipolar Junction Transistor)

**Sub-categories:**
- **Common Emitter (CE)** - Chân phát chung: 6 templates (BJT-CE-01 → BJT-CE-06)
  - Voltage divider bias, Fixed bias, Emitter degeneration, Externally biased
- **Common Base (CB)** - Chân base chung: 4 templates (BJT-CB-01 → BJT-CB-04)
  - Voltage divider, Fixed bias, Bypass/No bypass variants
- **Common Collector (CC)** - Chân collector chung (Emitter Follower): 4 templates (BJT-CC-01 → BJT-CC-04)
  - Buffer configurations, Voltage divider, Fixed bias

**Total:** 14 templates

---

### 2. **_index_mosfet.json** - MOSFET/FET Amplifiers
**Category:** `mosfet_amplifier`  
**Mô tả:** Các mạch khuếch đại dùng MOSFET/FET

**Sub-categories:**
- **Common Source (CS)** - Chân source chung: 6 templates (FET-CS-01 → FET-CS-06)
  - Voltage divider, Fixed gate, Externally biased, Bypass/Unbypassed variants
- **Common Drain (CD)** - Chân drain chung (Source Follower): 4 templates (FET-CD-01 → FET-CD-04)
  - Buffer configurations, Voltage divider, Fixed gate
- **Common Gate (CG)** - Chân gate chung: 6 templates (FET-CG-01 → FET-CG-06)
  - Voltage divider, Fixed gate, Externally biased, Gate bypass variants

**Total:** 16 templates

---

### 3. **_index_opamp.json** - Operational Amplifiers
**Category:** `opamp_circuit`  
**Mô tả:** Các mạch dùng Op-Amp (Operational Amplifier)

**Sub-categories:**
- **Inverting (Đảo)** - 4 templates (OP-01 → OP-04)
  - Dual supply, Single supply, AC coupled variants
- **Non-Inverting (Không đảo)** - 4 templates (OP-05 → OP-08)
  - Dual supply, Single supply, AC coupled variants
- **Differential (Vi sai)** - 2 templates (OP-09 → OP-10)
  - 4-resistor configuration, AC coupled
- **Instrumentation (Thuật toán đo lường)** - 3 templates (OP-11 → OP-13)
  - 3-OpAmp configurations, Single/Dual supply, AC coupled

**Total:** 13 templates

---

### 4. **_index_operation.json** - Power Operation Classes
**Category:** `power_amplifier_operation`  
**Mô tả:** Các mạch khuếch đại công suất theo class hoạt động

**Sub-categories:**
- **Class A** - 4 templates (CLASS-A-01 → CLASS-A-04)
  - Voltage divider, Fixed bias, Externally biased
- **Class AB** - 4 templates (CLASS-AB-01 → CLASS-AB-04)
  - Push-pull, Diode bias, DC/AC coupled
- **Class B** - 3 templates (CLASS-B-01 → CLASS-B-03)
  - Push-pull, No bias, Externally biased
- **Class C** - 4 templates (CLASS-C-01 → CLASS-C-04)
  - Tuned amplifiers, RF applications
- **Class D** - 4 templates (CLASS-D-01 → CLASS-D-04)
  - PWM, H-bridge, Half-bridge, LC filter variants

**Total:** 19 templates

---

### 5. **_index_special.json** - Special Configurations
**Category:** `special_amplifier`  
**Mô tả:** Các cấu hình đặc biệt và mạch nhiều tầng

**Sub-categories:**
- **Darlington Pair** - 4 templates (SPECIAL-DAR-01 → SPECIAL-DAR-04)
  - Voltage divider, Fixed bias, Externally biased
- **Multi-Stage** - 4 templates (SPECIAL-MS-01 → SPECIAL-MS-04)
  - CE-CC two-stage configurations, Various bias methods

**Total:** 8 templates

---

## Cấu Trúc JSON

Mỗi file index có cấu trúc:

```json
{
  "category": "tên_category",
  "description": "Mô tả ngắn gọn",
  "templates": [
    {
      "template_id": "ID-XX",
      "topology_type": "tên_topology",
      "sub_category": "phân_loại_con",
      "description": "Mô tả chi tiết",
      "file": "tên_file.json"
    }
  ],
  "total": số_lượng_templates
}
```

## Template ID Convention

| Category | Prefix | Example |
|----------|--------|---------|
| BJT | `BJT-CE-`, `BJT-CB-`, `BJT-CC-` | BJT-CE-01 |
| MOSFET | `FET-CS-`, `FET-CD-`, `FET-CG-` | FET-CS-01 |
| OpAmp | `OP-` | OP-01 |
| Operation Class | `CLASS-A-`, `CLASS-AB-`, `CLASS-B-`, `CLASS-C-`, `CLASS-D-` | CLASS-A-01 |
| Special | `SPECIAL-DAR-`, `SPECIAL-MS-` | SPECIAL-DAR-01 |

## Sử Dụng

### 1. Tìm template theo category:
```python
import json

# Load index
with open('_index_bjt.json') as f:
    bjt_index = json.load(f)

# Lọc theo sub_category
ce_templates = [t for t in bjt_index['templates'] if t['sub_category'] == 'common_emitter']
```

### 2. Load template chi tiết:
```python
# Từ template_id, lấy filename
template = next(t for t in bjt_index['templates'] if t['template_id'] == 'BJT-CE-01')
filename = template['file']

# Load file JSON chi tiết
with open(filename) as f:
    circuit_data = json.load(f)
```

## Migration từ Index Cũ

| File Cũ | File Mới | Ghi Chú |
|---------|----------|---------|
| `_index.json` | `_index_opamp.json` | OpAmp templates |
| `_index_power_amp.json` | `_index_operation.json` | Class A/AB/B/C templates |
| `_index_class_d.json` | `_index_operation.json` | Class D templates (merged) |
| `_index_special_amp.json` | `_index_special.json` | Darlington + Multi-stage |
| *(chưa có)* | `_index_bjt.json` | **MỚI** - BJT CE/CB/CC |
| *(chưa có)* | `_index_mosfet.json` | **MỚI** - MOSFET CS/CD/CG |

## Tổng Kết

**Tổng số templates:** 70 templates  
- BJT: 14
- MOSFET: 16
- OpAmp: 13
- Operation (Classes): 19
- Special: 8

Cấu trúc mới giúp:
- ✅ Phân loại rõ ràng theo loại linh kiện và topology
- ✅ Dễ dàng mở rộng thêm templates mới
- ✅ Hỗ trợ AI training và template matching
- ✅ Tìm kiếm nhanh theo sub_category
- ✅ Naming convention thống nhất

---

**Lưu ý:** Các file index cũ (`_index.json`, `_index_power_amp.json`, `_index_class_d.json`, `_index_special_amp.json`) vẫn được giữ lại để tương thích ngược. Khuyến nghị sử dụng các file index mới cho các tính năng mới.
