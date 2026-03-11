# Lộ trình Nâng cấp Hệ thống - Chi tiết File & Vị trí

**Version:** 2.0  
**Last Updated:** January 25, 2026  
**Status:** Production-Ready Roadmap

## 🎯 MỤC TIÊU TỔNG QUÁT

Nâng cấp hệ thống từ demo sang **production-ready (70-80%)** với:
- ✅ Sử dụng thư viện KiCad chuẩn (vendor subset symbols)
- ✅ Component catalog DB với 20-30 models
- ✅ Module hóa 10-15 topology (amplifier + oscillator)
- ✅ Symbol library management (parse, index, cache)
- ✅ API V2 với structured parameters
- ✅ Frontend refactoring (tách CSS/JS)
- ✅ Testing coverage >70%

## 📐 KIẾN TRÚC TỔNG QUAN SAU KHI HOÀN THÀNH

```
apps/api/
├── resources/                    # NEW: KiCad symbols vendor
│   └── kicad/
│       ├── symbols/              # Subset symbols
│       │   ├── Device.kicad_sym
│       │   ├── power.kicad_sym
│       │   ├── Transistor_BJT.kicad_sym
│       │   ├── Transistor_FET.kicad_sym
│       │   ├── Amplifier_Operational.kicad_sym
│       │   └── Timer.kicad_sym
│       └── kicad_lib_manifest.json
├── app/
│   ├── domains/circuits/
│   │   ├── topologies/           # NEW: Module hóa topology
│   │   │   ├── __init__.py
│   │   │   ├── base.py
│   │   │   ├── bjt/              # BJT topologies
│   │   │   ├── mosfet/           # MOSFET topologies
│   │   │   ├── opamp/            # OpAmp topologies
│   │   │   └── oscillators/      # Oscillator topologies
│   │   ├── component_library.py  # NEW
│   │   ├── entities.py           # UPDATED
│   │   ├── template_builder.py   # REFACTORED
│   │   ├── rules.py
│   │   └── ir.py
│   ├── infrastructure/
│   │   ├── kicad/                # NEW: Symbol management
│   │   │   ├── __init__.py
│   │   │   ├── symbol_parser.py
│   │   │   └── symbol_library.py
│   │   ├── exporters/
│   │   │   └── kicad_sch_serializer.py  # REFACTORED
│   │   └── persistence/
│   │       └── component_model_repo.py  # NEW
│   └── ...
```

---

## 📋 PHẦN 1: FILE CẦN CẬP NHẬT (SỬA CODE HIỆN TẠI)

### A. PYTHON FILES - Backend

#### 🔴 CRITICAL - Symbol Sourcing & Serialization

**1. `apps/api/app/domains/circuits/template_builder.py` (858 dòng)**
- **Vị trí cần sửa:**
  - Dòng 58-82: Class `BJTAmplifierConfig` 
    - ⚠️ **Action**: Đổi tên → `BJTAmplifierBuildConfig`
    - ⚠️ **Action**: Xóa fields `bjt_model`, `beta`, `rc`, `re`, `r1`, `r2`, `cin`, `cout`, `ce`
    - ✅ **Thêm**: Field `transistor: ComponentRef`
    - ✅ **Thêm**: Field `resistors: Optional[Dict[str, float]] = None`
    - ✅ **Thêm**: Field `capacitors: Optional[Dict[str, float]] = None`
    - ✅ **Thêm**: Field `build: BuildOptions`
    - ✅ **Thêm**: Method `__post_init__()` để init dict

    **➡️ ĐÃ HOÀN THÀNH ☑️**

  - Dòng 84-88: Class `ComponentRef`
    - ✅ **Thêm**: Field `library_id: Optional[str] = None`
    - ⚠️ **Action**: Đổi default `preference="typical"` → `"typ"`
    
    **➡️ ĐÃ HOÀN THÀNH ☑️**

  - Dòng 90-95: Class `BuildOptions`
    - ✅ **Thêm**: Field `resistor_series: Literal["E12", "E24", "E96"] = "E12"`
    - ✅ **Thêm**: Field `capacitor_series: Literal["E6", "E12", "E24"] = "E12"`
    - ⚠️ **Action**: Xóa comment tiếng Việt
    
    **➡️ ĐÃ HOÀN THÀNH ☑️**

  - Dòng 254-257: Class `BJTAmplifierBuilder.__init__`
    - ⚠️ **Action**: Đổi param type `config: BJTAmplifierConfig` → `config: BJTAmplifierBuildConfig`
    - ✅ **Thêm**: Field `self.component_library = ComponentLibrary()`

    **➡️ ĐÃ HOÀN THÀNH ☑️**

  - Dòng 280-720: Các method `_build_common_emitter()`, `_build_common_collector()`, `_build_common_base()`
    - ⚠️ **Tách logic**: Không lấy `cfg.bjt_model`, `cfg.beta` trực tiếp
    - ✅ **Thay bằng**: `cfg.transistor.model`, lookup beta từ ComponentLibrary
    - ⚠️ **Tách logic**: Không lấy `cfg.rc`, `cfg.r1`, etc. trực tiếp
    - ✅ **Thay bằng**: Gọi `self._get_resistor_value("RC", calculated_value)`
    - ✅ **Thêm method**: `_get_resistor_value(key: str, calculated: float) -> float`
    - ✅ **Thêm method**: `_get_capacitor_value(key: str, default: float) -> float`
    - ✅ **Thêm method**: `_get_bjt_beta() -> float` (lookup từ library)
    - ✅ **Cập nhật**: Mỗi Component cần có `library_id` từ ComponentLibrary

  - Dòng 1063-1120: Class `AmplifierFactory`
    - ⚠️ **Action**: Đổi return type của `create_bjt()` từ `BJTAmplifierConfig` → `BJTAmplifierBuildConfig`
    - ⚠️ **Tách logic**: Constructor của config cũ → config mới với dict

- **Lý do sửa**: Tách biệt component selection khỏi physics, hỗ trợ nhiều model, override linh hoạt

---

**2. `apps/api/app/domains/circuits/entities.py`**
- **Vị trí cần sửa:**
  - Class `Component` (khoảng dòng 100-150)
    - ✅ **Thêm field**: `library_id: Optional[str] = None`
    - ✅ **Thêm validation**: Trong `__post_init__()` check format "Library:Symbol"

- **Lý do sửa**: Component cần library_id để serializer biết symbol nào cần nhúng

---

**3. `apps/api/app/infrastructure/exporters/kicad_sch_serializer.py`**
- **⚠️ FILE QUAN TRỌNG NHẤT** - Quyết định render đẹp hay không
- **Vị trí cần sửa:**
  
  - **THÊM MỚI**: Method `_build_lib_symbols(circuit: Circuit) -> List[str]`
    - Logic:
      1. Collect tất cả unique `library_id` từ `circuit.components`
      2. For each library_id: lookup SymbolDefinition từ ComponentLibrary
      3. Serialize SymbolDefinition thành S-expression KiCad format
      4. Return list các symbol definitions
    - Vị trí đặt: Trước method `serialize()`

  - Method `serialize(circuit: Circuit) -> str` (khoảng dòng 50-100)
    - ✅ **Thêm vào đầu**: Gọi `lib_symbols = self._build_lib_symbols(circuit)`
    - ✅ **Thêm section**: Sau `(kicad_sch ...)` thêm `(lib_symbols ...lib_symbols...)`
    - ⚠️ **Thứ tự**: lib_symbols PHẢI đứng trước symbols (instances)

  - Method `_serialize_symbol(component: Component)` (khoảng dòng 150-250)
    - ⚠️ **NGỪNG tự vẽ**: Xóa logic tự gen graphics (rectangle, arc, pin)
    - ✅ **Thay bằng**: Reference library_id
    - Format mới: `(symbol (lib_id "Device:R") (at x y angle) (property "Reference" "R1") ...)`
    - ✅ **Lấy properties từ**: ComponentSpec (Value, Footprint)
    - ✅ **Apply**: `value_policy` khi set Value field

  - **THÊM MỚI**: Constructor nhận ComponentLibrary
    - `def __init__(self, component_library: ComponentLibrary = None):`
    - `self.component_library = component_library or ComponentLibrary()`

- **Lý do sửa**: Hiện tại tự vẽ symbol → render không đẹp, không đúng chuẩn. Cần nhúng symbol từ KiCad .kicad_sym

---

#### 🟡 MEDIUM PRIORITY - Application Layer

**4. `apps/api/app/application/circuits/dtos.py` (888 dòng)**
- **Vị trí cần sửa:**
  
  - **THÊM MỚI** (sau dòng 100): Class `GenerateFromTemplateRequest` (Pydantic)
    ```
    Fields:
    - template_id: str
    - circuit_name: Optional[str]
    - circuit_description: Optional[str]
    - parameters: TemplateParameters
    ```

  - **THÊM MỚI**: Class `TemplateParameters`
    ```
    Fields:
    - topology: str
    - vcc: Optional[float] = 12.0
    - gain_target: Optional[float] = None
    - transistor: Optional[ComponentRefDTO] = None
    - opamp: Optional[ComponentRefDTO] = None
    - resistors: Optional[Dict[str, float]] = None
    - capacitors: Optional[Dict[str, float]] = None
    - build_options: Optional[BuildOptionsDTO] = None
    ```

  - **THÊM MỚI**: Class `ComponentRefDTO`
    ```
    Fields:
    - model: str
    - preference: str = "typical"
    - manufacturer: Optional[str] = None
    - package: Optional[str] = None
    ```

  - **THÊM MỚI**: Class `BuildOptionsDTO`
    ```
    Fields:
    - include_input_coupling: bool = True
    - include_output_coupling: bool = True
    - include_emitter_bypass: bool = True
    - layout_style: str = "textbook"
    - resistor_series: str = "E12"
    - capacitor_series: str = "E12"
    ```

  - **THÊM MỚI**: Class `GenerationMetadata`
    ```
    Fields:
    - template_version: str = "2.0"
    - parameters_used: Dict[str, Any]
    - component_library_version: str
    - ai_agent_version: Optional[str]
    - prompt_used: Optional[str]
    - optimization_iterations: Optional[int]
    ```

  - Class `CircuitResponse` (khoảng dòng 200-250)
    - ✅ **Thêm field**: `generation_metadata: GenerationMetadata`

- **Lý do sửa**: DTO cần cấu trúc V2 để support dict overrides và metadata tracking

---

**5. `apps/api/app/application/circuits/use_cases/generate_circuit.py` (192 dòng)**
- **Vị trí cần sửa:**

  - Class `GenerateCircuitUseCase.__init__` (dòng 37-43)
    - ✅ **Thêm param**: `component_library: ComponentLibrary = None`
    - ✅ **Thêm field**: `self.component_library = component_library or ComponentLibrary()`

  - Method `execute()` (dòng 45-92)
    - ✅ **Thêm logic**: Validate component tồn tại trong library (nếu có transistor/opamp)
    - ✅ **Thêm logic**: Save generation metadata cùng circuit

  - Method `_generate_from_template()` (khoảng dòng 100-150)
    - ⚠️ **Tách logic**: Không hardcode BJTAmplifierConfig với từng field
    - ✅ **Thay bằng**: Convert DTO → Domain Config (map dict)
    - ✅ **Thêm method**: `_convert_dto_to_domain_config(template_id, parameters)`
    - ✅ **Thêm method**: `_convert_build_options(dto) -> BuildOptions`

- **Lý do sửa**: Use case cần biết ComponentLibrary để validate và convert DTO đúng

---

**6. `apps/api/app/application/circuits/prompt_analyzer.py`**
- **Vị trí cần sửa:**

  - **THÊM MỚI**: Method `analyze_v2(prompt: str) -> TemplateParameters`
    - Extract: topology, specs, component preferences
    - Return: TemplateParameters DTO

  - **THÊM MỚI**: Method `_extract_component_preferences(prompt: str) -> Dict`
    - Tìm model hints: "2N2222", "BC547", "LM358"
    - Tìm preference hints: "low noise", "high gain"
    - Tìm series hints: "E24", "1% resistor"

- **Lý do sửa**: AI cần parse component selection từ ngôn ngữ tự nhiên

---

#### 🟢 LOW PRIORITY - Infrastructure & API

**7. `apps/api/app/interfaces/http/routes/circuits.py`**
- **Vị trí cần sửa:**

  - **THÊM MỚI**: Endpoint POST `/api/v2/circuits/generate`
    - Params: `GenerateFromTemplateRequest`
    - Return: `CircuitResponse`

  - **THÊM MỚI**: Endpoint POST `/api/v2/circuits/generate/ai`
    - Params: `prompt: str`
    - Return: `CircuitResponse`
    - Note: Gọi CircuitGenerationAgent (Phase 7)

  - **THÊM MỚI**: Endpoint GET `/api/v2/components`
    - Query: category, manufacturer
    - Return: `List[ComponentSpec]`

  - **THÊM MỚI**: Endpoint GET `/api/v2/components/{model}`
    - Return: `ComponentSpec`

  - **THÊM MỚI**: Endpoint GET `/api/v2/circuits/templates`
    - Return: List template info

  - **GIỮ NGUYÊN**: Các endpoint V1 để backward compatibility

- **Lý do sửa**: API V2 cần endpoints mới cho component library và structured parameters

---

**8. `apps/api/app/infrastructure/exporters/kicad_sch_exporter.py`**
- **Vị trí cần sửa:**

  - Method `export()` (khoảng dòng 30-50)
    - ⚠️ **Cập nhật**: Pass ComponentLibrary vào KiCadSchSerializer
    - `serializer = KiCadSchSerializer(component_library=self.component_library)`

- **Lý do sửa**: Exporter cần inject ComponentLibrary vào serializer

---

**9. `apps/api/app/api/endpoints.py`**
- **Vị trí cần sửa:**
  - ⚠️ **Đổi tên file**: → `routes_v1_compat.py` (chỉ giữ V1 endpoints)
  - ⚠️ **Di chuyển**: Logic sang `interfaces/http/routes/`

- **Lý do sửa**: Cấu trúc cũ không rõ ràng, cần tách V1 và V2

---

**10. `apps/api/app/main.py`**
- **Vị trí cần sửa:**
  - ⚠️ **Include router**: Thêm `app.include_router(circuits_v2_router, prefix="/api/v2")`
  - ⚠️ **Include router**: Thêm `app.include_router(components_router, prefix="/api/v2")`

- **Lý do sửa**: Cần mount V2 API routes

---

### B. HTML FILES - Frontend

**11. `apps/api/static/demo.html` (372 dòng)**
- **⚠️ VẤN ĐỀ HIỆN TẠI:**
  - Dòng 17-24: CSS nằm trong `<style>` tag → Khó maintain
  - Dòng 198-372: JavaScript nằm trong `<script>` tag → Khó debug, test
  - Logic UI, API call, state management tất cả trong 1 file
  - Không tách components

- **HƯỚNG XỬ LÝ:**
  
  **Phase 1: Tách CSS**
  - Dòng 17-24: ⚠️ **Di chuyển** → `apps/api/static/css/demo.css`
  - Replace với: `<link rel="stylesheet" href="/static/css/demo.css">`

  **Phase 2: Tách JavaScript**
  - Dòng 198-372: ⚠️ **Di chuyển** → `apps/api/static/js/demo.js`
  - Replace với: `<script type="module" src="/static/js/demo.js"></script>`
  - Cấu trúc module:
    ```
    demo.js
    ├── state.js (Alpine.js state management)
    ├── api.js (API calls)
    └── utils.js (helpers)
    ```

  **Phase 3: Component-ize (Optional - Phase 6)**
  - Tách chat UI → `components/chat.js`
  - Tách circuit viewer → `components/circuit-viewer.js`
  - Tách sidebar controls → `components/controls.js`

  **Phase 4: Cập nhật API calls**
  - Function `sendPrompt()` (dòng 241): 
    - Đổi endpoint `/api/circuits/generate/from-prompt` → `/api/v2/circuits/generate/ai`
    - Đổi request body theo `GenerateFromTemplateRequest`
  
  - Function `answerQuestions()` (dòng 267):
    - Cập nhật format theo V2 DTOs

  - Function `renderCircuit()` (dòng 318):
    - Cập nhật để hiển thị `generation_metadata`

- **Lý do sửa**: Code quá dài, khó maintain, không theo best practices

---

**12. `apps/api/static/viewer.html` (557 dòng)**
- **⚠️ VẤN ĐỀ HIỆN TẠI:**
  - Dòng 8-365: CSS nằm trong `<style>` → 357 dòng CSS!
  - Dòng 366-557: JavaScript nằm trong `<script>` → 191 dòng JS!
  - Không có separation of concerns

- **HƯỚNG XỬ LÝ:**

  **Phase 1: Tách CSS**
  - Dòng 8-365: ⚠️ **Di chuyển** → `apps/api/static/css/viewer.css`
  - Chia nhỏ CSS theo component:
    ```
    viewer.css
    ├── header.css
    ├── controls.css
    ├── info-panel.css
    ├── kicanvas-embed.css
    └── status.css
    ```

  **Phase 2: Tách JavaScript**
  - Dòng 366-557: ⚠️ **Di chuyển** → `apps/api/static/js/viewer.js`
  - Tách module:
    ```
    viewer.js (main orchestrator)
    ├── kicanvas-loader.js (KiCanvas initialization)
    ├── circuit-api.js (API calls: export, validate, download)
    ├── ui-controls.js (button handlers)
    └── status-manager.js (status messages)
    ```

  **Phase 3: Cập nhật API endpoints**
  - Function `exportCircuit()` (dòng 417):
    - Check if circuit dùng V2 → call `/api/v2/circuits/export/...`
  
  - Function `loadCircuit()` (dòng 378):
    - Support cả V1 và V2 circuit IDs

- **Lý do sửa**: File quá lớn, khó debug, CSS/JS lẫn lộn trong HTML

---

**13. `apps/api/static/kicad_demo/demo.html`**
- **HƯỚNG XỬ LÝ:**
  - ⚠️ **Đánh giá**: Nếu chỉ dùng để test → giữ nguyên
  - ⚠️ **Nếu dùng production**: Apply cùng pattern như `demo.html`

---

**14. `apps/api/static/kicad_viewer/debug_render.html`**
- **HƯỚNG XỬ LÝ:**
  - ⚠️ **Chỉ dùng debug**: Có thể giữ nguyên hoặc di chuyển vào `/debug/` folder

---

### C. JAVASCRIPT FILES - Existing

**15. `apps/api/static/kicanvas/kicanvas.js`**
- **KHÔNG SỬA** - External library

**16. `apps/api/static/kicanvas/kicanvas1.js`**
- **KHÔNG SỬA** - External library backup

---

## 📁 PHẦN 2: FILE & FOLDER CẦN TẠO MỚI

### A. RESOURCES - KiCad Symbol Vendor ⭐ CRITICAL FIRST

**1. `apps/api/resources/kicad/symbols/` (folder mới)**

**Subset symbols cần vendor** (10-30 symbols cho MVP):

**1.1. Device.kicad_sym** (Passive components)
- Resistor: `Device:R`, `Device:R_Small`
- Capacitor: `Device:C`, `Device:C_Polarized`, `Device:C_Small`
- Inductor: `Device:L`, `Device:L_Small`
- Diode: `Device:D`, `Device:D_Zener`

**1.2. power.kicad_sym** (Power symbols)
- `power:GND`, `power:GNDA`, `power:GNDD`
- `power:VCC`, `power:VDD`, `power:+12V`, `power:+5V`
- `power:VEE`, `power:VSS`, `power:-12V`

**1.3. Transistor_BJT.kicad_sym** (BJT symbols)
- NPN: `Transistor_BJT:Q_NPN_BCE`, `Transistor_BJT:Q_NPN_CBE`
- PNP: `Transistor_BJT:Q_PNP_BCE`, `Transistor_BJT:Q_PNP_CBE`

**1.4. Transistor_FET.kicad_sym** (MOSFET symbols)
- NMOS: `Transistor_FET:Q_NMOS_GDS`, `Transistor_FET:Q_NMOS_DGS`
- PMOS: `Transistor_FET:Q_PMOS_GDS`, `Transistor_FET:Q_PMOS_DGS`

**1.5. Amplifier_Operational.kicad_sym** (OpAmp symbols)
- `Amplifier_Operational:LM741`
- `Amplifier_Operational:TL081`
- `Amplifier_Operational:LM358`

**1.6. Timer.kicad_sym** (555 timer)
- `Timer:NE555`

**Cách lấy symbols:**
1. Clone repo: `git clone https://gitlab.com/kicad/libraries/kicad-symbols.git`
2. Checkout tag stable: `git checkout 8.0` (hoặc version KiCad đang dùng)
3. Copy các file .kicad_sym cần thiết vào `resources/kicad/symbols/`
4. Tạo manifest file để track version

---

**2. `apps/api/resources/kicad/kicad_lib_manifest.json`** ⭐
```json
{
  "version": "2.0.0",
  "kicad_version": "8.0",
  "library_source": {
    "repo": "https://gitlab.com/kicad/libraries/kicad-symbols.git",
    "tag": "8.0.0",
    "commit": "abc123...",
    "imported_at": "2026-01-25T00:00:00Z"
  },
  "vendored_libraries": [
    {
      "name": "Device",
      "file": "Device.kicad_sym",
      "symbols_count": 8,
      "symbols": ["R", "C", "C_Polarized", "L", "D", "D_Zener"]
    },
    {
      "name": "power",
      "file": "power.kicad_sym",
      "symbols_count": 9,
      "symbols": ["GND", "VCC", "VDD", "+12V", "+5V", "VEE", "VSS", "-12V"]
    },
    {
      "name": "Transistor_BJT",
      "file": "Transistor_BJT.kicad_sym",
      "symbols_count": 4,
      "symbols": ["Q_NPN_BCE", "Q_NPN_CBE", "Q_PNP_BCE", "Q_PNP_CBE"]
    },
    {
      "name": "Transistor_FET",
      "file": "Transistor_FET.kicad_sym",
      "symbols_count": 4,
      "symbols": ["Q_NMOS_GDS", "Q_NMOS_DGS", "Q_PMOS_GDS", "Q_PMOS_DGS"]
    },
    {
      "name": "Amplifier_Operational",
      "file": "Amplifier_Operational.kicad_sym",
      "symbols_count": 3,
      "symbols": ["LM741", "TL081", "LM358"]
    },
    {
      "name": "Timer",
      "file": "Timer.kicad_sym",
      "symbols_count": 1,
      "symbols": ["NE555"]
    }
  ],
  "total_symbols": 29,
  "notes": "Subset for amplifier + oscillator circuits MVP"
}
```

---

### B. DOMAIN LAYER - Python

**3. `apps/api/app/domains/circuits/component_library.py`** ⭐ CRITICAL
```
Nội dung:
- Class ComponentCategory (Enum)
  - RESISTOR, CAPACITOR, INDUCTOR, DIODE
  - BJT_NPN, BJT_PNP, MOSFET_N, MOSFET_P
  - OPAMP, IC_TIMER

- Class ComponentSpec (dataclass)
  - model: str (e.g., "2N3904", "LM741")
  - category: ComponentCategory
  - library_id: str (e.g., "Transistor_BJT:2N3904")
  - description: str
  - parameters: Dict[str, Any] (beta, vbe, gm, etc.)
  - footprint: Optional[str]
  - datasheet_url: Optional[str]
  - manufacturer: Optional[str]
  - spice_model: Optional[str]

- Class ComponentLibrary (singleton)
  - Method: get(model: str) -> ComponentSpec
  - Method: search(category, manufacturer) -> List[ComponentSpec]
  - Method: add_custom(spec: ComponentSpec)
  - Method: list_by_category(category) -> List[ComponentSpec]
  - Field: _components: Dict[str, ComponentSpec]
  - Method: _load_defaults() - seed 20-30 models
  
**Default components to seed:**
- BJT NPN: 2N3904, BC547, 2N2222, 2N3055
- BJT PNP: 2N3906, BC557, 2N2907
- MOSFET N: 2N7000, BS170, IRF540
- MOSFET P: BS250, IRF9540
- OpAmp: LM741, TL081, LM358, TL072, LM324
- Timer: NE555
- Passives: Generic R, C, L, D
```

**Vị trí**: `apps/api/app/domains/circuits/component_library.py`

---

**4. `apps/api/app/domains/circuits/topologies/` (folder mới)** ⭐

Tổ chức topology modules theo hierarchy:

```
topologies/
├── __init__.py
├── base.py                      # BaseTopologyBuilder abstract class
├── bjt/
│   ├── __init__.py
│   ├── common_emitter.py        # CE amplifier
│   ├── common_collector.py      # CC (emitter follower)
│   ├── common_base.py           # CB amplifier
│   └── cascode.py               # Cascode (CE+CB)
├── mosfet/
│   ├── __init__.py
│   ├── common_source.py         # CS amplifier
│   ├── common_drain.py          # CD (source follower)
│   └── common_gate.py           # CG amplifier
├── opamp/
│   ├── __init__.py
│   ├── inverting.py             # Inverting amplifier
│   ├── non_inverting.py         # Non-inverting amplifier
│   ├── voltage_follower.py      # Buffer
│   └── differential.py          # Differential amplifier
└── oscillators/
    ├── __init__.py
    ├── wien_bridge.py           # Wien bridge oscillator
    ├── rc_phase_shift.py        # RC phase shift oscillator
    ├── astable_555.py           # 555 astable
    └── schmitt_trigger.py       # Schmitt trigger RC
```

**4.1. `base.py`** - Base class cho tất cả topologies
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class TopologyConfig:
    """Base config for all topologies"""
    topology_type: str
    vcc: float = 12.0
    component_library: Optional['ComponentLibrary'] = None

class BaseTopologyBuilder(ABC):
    """Abstract base for topology builders"""
    
    def __init__(self, config: TopologyConfig):
        self.config = config
        self.component_library = config.component_library or ComponentLibrary()
    
    @abstractmethod
    def build(self) -> Circuit:
        """Build circuit from config"""
        pass
    
    @abstractmethod
    def validate_config(self) -> bool:
        """Validate configuration"""
        pass
    
    def _get_component_spec(self, model: str) -> ComponentSpec:
        """Lookup component from library"""
        return self.component_library.get(model)
```

**4.2. `bjt/common_emitter.py`** - Example topology
```python
from ..base import BaseTopologyBuilder, TopologyConfig
from dataclasses import dataclass

@dataclass
class CEAmplifierConfig(TopologyConfig):
    topology_type: str = "CE"
    transistor_model: str = "2N3904"
    gain_target: float = 10.0
    ic_target: float = 1.5e-3
    # ... other params

class CEAmplifierBuilder(BaseTopologyBuilder):
    def __init__(self, config: CEAmplifierConfig):
        super().__init__(config)
        self.config = config
    
    def build(self) -> Circuit:
        # Build CE circuit
        transistor_spec = self._get_component_spec(self.config.transistor_model)
        # ... build logic
        return circuit
    
    def validate_config(self) -> bool:
        # Validate CE specific constraints
        return True
```

**4.3. Topology Factory** - `topologies/__init__.py`
```python
from .base import BaseTopologyBuilder
from .bjt.common_emitter import CEAmplifierBuilder
from .bjt.common_collector import CCAmplifierBuilder
# ... imports

class TopologyFactory:
    """Factory for creating topology builders"""
    
    _registry = {
        "CE": CEAmplifierBuilder,
        "CC": CCAmplifierBuilder,
        "CB": CBAmplifierBuilder,
        "CS": CSAmplifierBuilder,
        "CD": CDAmplifierBuilder,
        "CG": CGAmplifierBuilder,
        "inverting": InvertingOpAmpBuilder,
        "non_inverting": NonInvertingOpAmpBuilder,
        "wien": WienBridgeBuilder,
        "rc_phase": RCPhaseShiftBuilder,
        "555_astable": Astable555Builder,
    }
    
    @classmethod
    def create(cls, topology_type: str, config: TopologyConfig) -> BaseTopologyBuilder:
        builder_class = cls._registry.get(topology_type)
        if not builder_class:
            raise ValueError(f"Unknown topology: {topology_type}")
        return builder_class(config)
    
    @classmethod
    def list_topologies(cls) -> list[str]:
        return list(cls._registry.keys())
```

---

### C. INFRASTRUCTURE LAYER - Python

**5. `apps/api/app/infrastructure/kicad/` (folder mới)**

**5.1. `apps/api/app/infrastructure/kicad/__init__.py`**
```python
from .symbol_parser import KiCadSymbolParser, SymbolDefinition, PinDefinition
from .symbol_library import SymbolLibrary

__all__ = ['KiCadSymbolParser', 'SymbolDefinition', 'PinDefinition', 'SymbolLibrary']
```

**5.2. `apps/api/app/infrastructure/kicad/symbol_parser.py`** ⭐ CRITICAL
```python
"""KiCad symbol parser for .kicad_sym files (S-expression format)"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import sexpdata

@dataclass
class PinDefinition:
    """Represents a pin in a KiCad symbol"""
    number: str
    name: str
    type: str  # input, output, bidirectional, power_in, power_out, etc.
    position: Tuple[float, float]
    length: float
    direction: str  # up, down, left, right

@dataclass
class SymbolDefinition:
    """Represents a complete KiCad symbol"""
    library_name: str
    symbol_name: str
    library_id: str  # "Device:R"
    pins: List[PinDefinition]
    graphics: str  # S-expression string for graphics
    properties: Dict[str, str]  # Reference, Value, Footprint, etc.
    raw_sexp: str  # Full S-expression for embedding

class KiCadSymbolParser:
    """Parser for KiCad .kicad_sym files"""
    
    def __init__(self, library_path: Path):
        self.library_path = library_path
        self._symbols_cache: Dict[str, SymbolDefinition] = {}
    
    def parse_library(self, lib_name: str) -> Dict[str, SymbolDefinition]:
        """Parse entire .kicad_sym file
        
        Args:
            lib_name: Library name (e.g., "Device")
            
        Returns:
            Dict mapping symbol_name to SymbolDefinition
        """
        lib_file = self.library_path / f"{lib_name}.kicad_sym"
        if not lib_file.exists():
            raise FileNotFoundError(f"Library not found: {lib_file}")
        
        with open(lib_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse S-expression
        try:
            sexp = sexpdata.loads(content)
        except Exception as e:
            raise ValueError(f"Failed to parse {lib_file}: {e}")
        
        symbols = {}
        # Extract symbols from (kicad_symbol_lib ...)
        for item in sexp[1:]:  # Skip first element (kicad_symbol_lib)
            if isinstance(item, list) and item[0] == sexpdata.Symbol('symbol'):
                symbol_def = self._parse_symbol_sexp(item, lib_name)
                symbols[symbol_def.symbol_name] = symbol_def
                self._symbols_cache[symbol_def.library_id] = symbol_def
        
        return symbols
    
    def get_symbol(self, library_id: str) -> SymbolDefinition:
        """Get symbol by library_id (e.g., "Device:R")
        
        Args:
            library_id: Format "LibraryName:SymbolName"
            
        Returns:
            SymbolDefinition
        """
        if library_id in self._symbols_cache:
            return self._symbols_cache[library_id]
        
        # Parse library if not cached
        lib_name, symbol_name = library_id.split(':')
        symbols = self.parse_library(lib_name)
        
        if symbol_name not in symbols:
            raise ValueError(f"Symbol not found: {library_id}")
        
        return symbols[symbol_name]
    
    def _parse_symbol_sexp(self, sexp, lib_name: str) -> SymbolDefinition:
        """Parse individual symbol S-expression
        
        Args:
            sexp: S-expression list
            lib_name: Library name
            
        Returns:
            SymbolDefinition
        """
        # Extract symbol name
        symbol_name = str(sexp[1]).strip('"')
        library_id = f"{lib_name}:{symbol_name}"
        
        # Extract pins
        pins = []
        for item in sexp:
            if isinstance(item, list) and item[0] == sexpdata.Symbol('pin'):
                pin = self._parse_pin(item)
                pins.append(pin)
        
        # Extract properties
        properties = {}
        for item in sexp:
            if isinstance(item, list) and item[0] == sexpdata.Symbol('property'):
                prop_name = str(item[1]).strip('"')
                prop_value = str(item[2]).strip('"')
                properties[prop_name] = prop_value
        
        # Store raw S-expression as string for embedding
        raw_sexp = sexpdata.dumps(sexp)
        
        # Extract graphics (simplified - store as string)
        graphics = raw_sexp
        
        return SymbolDefinition(
            library_name=lib_name,
            symbol_name=symbol_name,
            library_id=library_id,
            pins=pins,
            graphics=graphics,
            properties=properties,
            raw_sexp=raw_sexp
        )
    
    def _parse_pin(self, pin_sexp) -> PinDefinition:
        """Parse pin S-expression
        
        Args:
            pin_sexp: Pin S-expression
            
        Returns:
            PinDefinition
        """
        # Simplified pin parsing
        # Real implementation needs to extract all pin attributes
        return PinDefinition(
            number="1",
            name="Pin",
            type="passive",
            position=(0.0, 0.0),
            length=2.54,
            direction="left"
        )

```

**Dependency**: Add to `requirements.txt`:
```
sexpdata==1.0.0
```

**5.3. `apps/api/app/infrastructure/kicad/symbol_library.py`** ⭐ CRITICAL
```python
"""Symbol library management with caching"""

from pathlib import Path
from typing import Dict, Optional
from .symbol_parser import KiCadSymbolParser, SymbolDefinition
from app.core.config import get_settings

class SymbolLibrary:
    """Singleton for symbol library management"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            settings = get_settings()
            self.library_path = Path(settings.base_dir) / "resources" / "kicad" / "symbols"
            self.parser = KiCadSymbolParser(self.library_path)
            self._cache: Dict[str, SymbolDefinition] = {}
            self._load_manifest()
            self._build_index()
            SymbolLibrary._initialized = True
    
    def _load_manifest(self):
        """Load kicad_lib_manifest.json"""
        manifest_file = self.library_path.parent / "kicad_lib_manifest.json"
        if manifest_file.exists():
            import json
            with open(manifest_file, 'r') as f:
                self.manifest = json.load(f)
        else:
            self.manifest = {}
    
    def _build_index(self):
        """Build index of all symbols at startup"""
        if not self.manifest:
            return
        
        for lib_info in self.manifest.get('vendored_libraries', []):
            lib_name = lib_info['name']
            try:
                symbols = self.parser.parse_library(lib_name)
                self._cache.update({sym.library_id: sym for sym in symbols.values()})
            except Exception as e:
                print(f"Warning: Failed to load library {lib_name}: {e}")
    
    def get_symbol(self, library_id: str) -> Optional[SymbolDefinition]:
        """Get symbol by library_id with caching
        
        Args:
            library_id: Format "LibraryName:SymbolName"
            
        Returns:
            SymbolDefinition or None
        """
        if library_id in self._cache:
            return self._cache[library_id]
        
        try:
            symbol = self.parser.get_symbol(library_id)
            self._cache[library_id] = symbol
            return symbol
        except Exception:
            return None
    
    def list_symbols(self, library_name: Optional[str] = None) -> list[str]:
        """List all available symbol IDs
        
        Args:
            library_name: Optional filter by library
            
        Returns:
            List of library_id strings
        """
        if library_name:
            return [lid for lid in self._cache.keys() if lid.startswith(f"{library_name}:")]
        return list(self._cache.keys())
    
    def get_stats(self) -> dict:
        """Get library statistics"""
        return {
            "total_symbols": len(self._cache),
            "libraries": len(set(lid.split(':')[0] for lid in self._cache.keys())),
            "manifest_version": self.manifest.get('version', 'unknown')
        }
```

---

**6. `apps/api/app/infrastructure/db/repositories/` (folder hiện có)**

**6.1. `apps/api/app/infrastructure/db/repositories/component_library_repository.py`**
```
Nội dung:
- Class ComponentLibraryRepository
  - Method: get_by_model(model: str) -> ComponentSpec
  - Method: search(category, manufacturer) -> List[ComponentSpec]
  - Method: add_custom(spec: ComponentSpec, user_id: str)
  - Method: get_all() -> List[ComponentSpec]
```

**3.2. Cập nhật `apps/api/app/infrastructure/db/repositories/__init__.py`**
- Export ComponentLibraryRepository

---

### C. APPLICATION LAYER - Python

**4. `apps/api/app/application/ai/` (folder mới)**

**4.1. `apps/api/app/application/ai/__init__.py`**

**4.2. `apps/api/app/application/ai/circuit_generation_agent.py`** (Phase 7)
```
Nội dung:
- Class CircuitGenerationAgent
  - Method: generate_from_natural_language(prompt, user_id)
  - Method: _parse_requirements(prompt) -> Dict
  - Method: _select_optimal_component(requirements) -> ComponentSpec
  - Method: _generate_initial_design(requirements, component)
  - Method: _optimize_design(design, requirements)
```

---

### D. DATABASE - SQL Migrations

**5. `database/migrations/` (folder mới)**

**5.1. `database/migrations/001_initial_schema.sql`**
- Extract từ `database/db_circuit.sql` hiện tại
- Chỉ giữ phần tạo tables cơ bản

**5.2. `database/migrations/002_add_component_library.sql`**
```sql
-- Component Library Table
CREATE TABLE component_library (...);

-- Circuit Generation Metadata Table
CREATE TABLE circuit_generation_metadata (...);

-- Update circuits table
ALTER TABLE circuits ADD COLUMN template_id VARCHAR(100);
ALTER TABLE circuits ADD COLUMN generation_version VARCHAR(20);
```

**5.3. `database/migrations/003_seed_component_library.sql`**
```sql
-- Insert default components
INSERT INTO component_library (model, library_id, ...) VALUES
('2N3904', 'Transistor_BJT:2N3904', ...),
('BC547', 'Transistor_BJT:BC547', ...),
...
```

---

### E. FRONTEND - CSS Files

**6. `apps/api/static/css/` (folder mới)**

**6.1. `apps/api/static/css/demo.css`**
```css
/* Extracted from demo.html lines 17-24 */
/* Custom scrollbar */
::-webkit-scrollbar { ... }

/* KiCanvas embed styles */
kicanvas-embed { ... }
```

**6.2. `apps/api/static/css/viewer.css`**
```css
/* Extracted from viewer.html lines 8-365 */
/* Base styles */
* { ... }
body { ... }

/* Component styles */
.header { ... }
.controls { ... }
.info-panel { ... }
...
```

**6.3. `apps/api/static/css/components/` (subfolder)**
- `header.css`
- `controls.css`
- `info-panel.css`
- `status.css`

---

### F. FRONTEND - JavaScript Files

**7. `apps/api/static/js/` (folder mới)**

**7.1. `apps/api/static/js/demo.js`**
```javascript
// Main app entry
import { createAppState } from './demo/state.js';
import { setupAPI } from './demo/api.js';
import { initUI } from './demo/ui.js';

export function app() {
  return createAppState();
}
```

**7.2. `apps/api/static/js/demo/` (subfolder)**
- `state.js` - Alpine.js state management
- `api.js` - API calls (sendPrompt, answerQuestions, etc.)
- `ui.js` - UI helpers (renderCircuit, addLog, etc.)
- `utils.js` - Utility functions

**7.3. `apps/api/static/js/viewer.js`**
```javascript
// Main viewer entry
import { KiCanvasLoader } from './viewer/kicanvas-loader.js';
import { CircuitAPI } from './viewer/circuit-api.js';
import { UIControls } from './viewer/ui-controls.js';
import { StatusManager } from './viewer/status-manager.js';

// Initialize viewer
const loader = new KiCanvasLoader();
const api = new CircuitAPI();
...
```

**7.4. `apps/api/static/js/viewer/` (subfolder)**
- `kicanvas-loader.js` - KiCanvas initialization
- `circuit-api.js` - API wrapper (export, validate, download)
- `ui-controls.js` - Button handlers
- `status-manager.js` - Status message management

**7.5. `apps/api/static/js/shared/` (subfolder - Common utilities)**
- `api-client.js` - Base API client
- `logger.js` - Console logging wrapper
- `validators.js` - Input validation

---

### G. TESTING FILES

**8. `apps/api/tests/infrastructure/kicad/` (folder mới)**

**8.1. `apps/api/tests/infrastructure/kicad/__init__.py`**

**8.2. `apps/api/tests/infrastructure/kicad/test_symbol_parser.py`**
```python
# Test KiCadSymbolParser
- test_parse_device_library()
- test_parse_transistor_bjt_library()
- test_get_symbol_by_library_id()
- test_parse_pin_extraction()
- test_invalid_library_name()
```

**8.3. `apps/api/tests/infrastructure/test_symbol_integration.py`**
```python
# End-to-end symbol sourcing test
- test_symbol_sourcing_pipeline()
- test_lib_symbols_section_generation()
- test_kicad_cli_validation()
```

---

**9. `apps/api/tests/domain/test_component_library.py`**
```python
# Test ComponentLibrary
- test_get_component_by_model()
- test_search_by_category()
- test_add_custom_component()
- test_library_id_format()
```

---

### H. SCRIPTS & UTILITIES

**10. `apps/api/scripts/validate_render.py`** (mới)
```python
# Validation script using kicad-cli
- generate_test_circuit()
- export_with_kicad_cli()
- validate_svg_output()
- compare_with_kicanvas()
```

**11. `apps/api/scripts/seed_component_library.py`** (mới)
```python
# Seed ComponentLibrary with defaults
- parse_kicad_libraries()
- populate_database()
- generate_symbol_hash()
```

---

### I. DOCUMENTATION

**12. `docs/api/` (folder mới)**
- `v2_endpoints.md` - API V2 documentation
- `component_library_api.md` - Component search/query docs
- `migration_guide.md` - V1 → V2 migration guide

**13. `docs/developer/` (folder mới)**
- `symbol_sourcing.md` - How symbol sourcing works
- `adding_components.md` - How to add new components
- `render_debugging.md` - How to debug render issues

---

## 🗺️ PHẦN 3: LỘ TRÌNH TRIỂN KHAI CHI TIẾT

### 📌 OVERVIEW - Critical Path

```
Week 0: Preparation
   ↓
Week 1-2: PHASE 1 - Vendor KiCad Symbols + Symbol Parser ⭐ CRITICAL
   ↓
Week 2-3: PHASE 2 - Component Library + Domain Updates
   ↓
Week 3-4: PHASE 3 - Serializer Refactoring ⭐ CRITICAL
   ↓
Week 4-5: PHASE 4 - Topology Modules (MVP: 10 topologies)
   ↓
Week 5-6: PHASE 5 - Application Layer DTOs + Use Cases
   ↓
Week 6-7: PHASE 6 - API V2 Endpoints
   ↓
Week 7-8: PHASE 7 - Database + Persistence
   ↓
Week 8-9: PHASE 8 - Frontend Refactoring
   ↓
Week 9-10: PHASE 9 - Testing + Validation
   ↓
Week 10-11: PHASE 10 - Documentation + Deployment
```

---

### PHASE 0: Chuẩn bị (Week 0) ⚙️

**Mục tiêu**: Setup môi trường, backup code hiện tại

**Tasks:**

1. **Backup code hiện tại**
   ```bash
   git checkout -b backup-demo-v1
   git push origin backup-demo-v1
   git checkout main
   git checkout -b feature/vendor-kicad-symbols
   ```

2. **Tạo folder structure**
   ```bash
   mkdir -p apps/api/resources/kicad/symbols
   mkdir -p apps/api/app/domains/circuits/topologies/bjt
   mkdir -p apps/api/app/domains/circuits/topologies/mosfet
   mkdir -p apps/api/app/domains/circuits/topologies/opamp
   mkdir -p apps/api/app/domains/circuits/topologies/oscillators
   mkdir -p apps/api/app/infrastructure/kicad
   mkdir -p apps/api/tests/infrastructure/kicad
   mkdir -p apps/api/tests/domain/topologies
   ```

3. **Update dependencies**
   ```bash
   # Add to requirements.txt
   sexpdata==1.0.0
   
   # Install
   pip install sexpdata
   ```

4. **Verify KiCad CLI installation**
   ```bash
   # Windows
   kicad-cli version
   
   # If not found, install KiCad 8.0+
   ```

**Deliverable**: 
- ✅ Backup branch created
- ✅ Folder structure ready
- ✅ Dependencies installed
- ✅ KiCad CLI available

---

### PHASE 1: Vendor KiCad Symbols + Symbol Parser (Week 1-2) ⭐ CRITICAL

**Mục tiêu**: Có thư viện symbol chuẩn và parser hoạt động

#### Week 1: Vendor Symbols

**Day 1-2: Clone và copy symbols**
```bash
# Clone KiCad symbols repo
cd /tmp
git clone https://gitlab.com/kicad/libraries/kicad-symbols.git
cd kicad-symbols
git checkout 8.0  # hoặc version phù hợp

# Copy symbols cần thiết
cp Device.kicad_sym ~/Work/thesis/electronic-chatbot/apps/api/resources/kicad/symbols/
cp power.kicad_sym ~/Work/thesis/electronic-chatbot/apps/api/resources/kicad/symbols/
cp Transistor_BJT.kicad_sym ~/Work/thesis/electronic-chatbot/apps/api/resources/kicad/symbols/
cp Transistor_FET.kicad_sym ~/Work/thesis/electronic-chatbot/apps/api/resources/kicad/symbols/
cp Amplifier_Operational.kicad_sym ~/Work/thesis/electronic-chatbot/apps/api/resources/kicad/symbols/
cp Timer.kicad_sym ~/Work/thesis/electronic-chatbot/apps/api/resources/kicad/symbols/
```

**Day 3: Tạo manifest file**
- Tạo `kicad_lib_manifest.json` (theo template ở Phần 2)
- Ghi rõ version, commit hash, imported date
- Document tất cả symbols đã vendor

**Day 4-5: Verify symbols**
```bash
# Open mỗi file .kicad_sym bằng text editor
# Kiểm tra format S-expression đúng
# Kiểm tra có symbols cần thiết không (Device:R, Device:C, etc.)
```

**Files created:**
- ✅ `resources/kicad/symbols/*.kicad_sym` (6 files)
- ✅ `resources/kicad/kicad_lib_manifest.json`

#### Week 2: Symbol Parser

**Day 1-3: Implement symbol_parser.py**
- Tạo `infrastructure/kicad/symbol_parser.py`
- Implement `PinDefinition`, `SymbolDefinition` dataclasses
- Implement `KiCadSymbolParser` class
- Method `parse_library()` - parse S-expression
- Method `get_symbol()` - get individual symbol
- Method `_parse_symbol_sexp()` - extract symbol data
- Method `_parse_pin()` - extract pin data

**Day 4: Implement symbol_library.py**
- Tạo `infrastructure/kicad/symbol_library.py`
- Implement `SymbolLibrary` singleton
- Method `_load_manifest()` - load manifest
- Method `_build_index()` - build symbol index at startup
- Method `get_symbol()` - lookup with cache
- Method `list_symbols()` - list available symbols

**Day 5: Unit tests**
- Tạo `tests/infrastructure/kicad/test_symbol_parser.py`
- Test parse Device.kicad_sym
- Test parse Transistor_BJT.kicad_sym
- Test get_symbol("Device:R")
- Test get_symbol("Transistor_BJT:2N3904")

**Files created:**
- ✅ `app/infrastructure/kicad/__init__.py`
- ✅ `app/infrastructure/kicad/symbol_parser.py`
- ✅ `app/infrastructure/kicad/symbol_library.py`
- ✅ `tests/infrastructure/kicad/test_symbol_parser.py`

**Test command:**
```bash
pytest tests/infrastructure/kicad/ -v
```

**Deliverable**: 
- ✅ 6 symbol files vendored
- ✅ Manifest file created
- ✅ SymbolParser working
- ✅ SymbolLibrary singleton working
- ✅ Unit tests passing

---

### PHASE 2: Component Library + Domain Updates (Week 2-3)

**Mục tiêu**: Component có library_id, ComponentLibrary working

#### Week 2 (cont'd) - Day 6-7: Component Library

**Day 6: Implement component_library.py**
- Tạo `domains/circuits/component_library.py`
- Implement `ComponentCategory` enum
- Implement `ComponentSpec` dataclass
- Implement `ComponentLibrary` class
- Method `_load_defaults()` - seed 20-30 models

**Default components:**
```python
# BJT NPN
ComponentSpec(model="2N3904", category=BJT_NPN, library_id="Transistor_BJT:2N3904", 
              parameters={"beta": 100, "vbe": 0.7, "ic_max": 0.2})
ComponentSpec(model="BC547", category=BJT_NPN, library_id="Transistor_BJT:BC547",
              parameters={"beta": 110, "vbe": 0.65, "ic_max": 0.1})
ComponentSpec(model="2N2222", category=BJT_NPN, library_id="Transistor_BJT:2N2222",
              parameters={"beta": 120, "vbe": 0.7, "ic_max": 0.8})

# BJT PNP
ComponentSpec(model="2N3906", category=BJT_PNP, library_id="Transistor_BJT:2N3906",
              parameters={"beta": 100, "vbe": -0.7, "ic_max": 0.2})
ComponentSpec(model="BC557", category=BJT_PNP, library_id="Transistor_BJT:BC557",
              parameters={"beta": 110, "vbe": -0.65, "ic_max": 0.1})

# MOSFET N
ComponentSpec(model="2N7000", category=MOSFET_N, library_id="Transistor_FET:2N7000",
              parameters={"vth": 2.1, "rds_on": 5.0, "id_max": 0.2})

# OpAmp
ComponentSpec(model="LM741", category=OPAMP, library_id="Amplifier_Operational:LM741",
              parameters={"gbw": 1e6, "slew_rate": 0.5e6, "input_offset": 2e-3})
ComponentSpec(model="TL081", category=OPAMP, library_id="Amplifier_Operational:TL081",
              parameters={"gbw": 3e6, "slew_rate": 13e6, "input_offset": 3e-3})

# ... thêm 15-20 models nữa
```

**Day 7: Unit tests**
- Tạo `tests/domain/test_component_library.py`
- Test get_component("2N3904")
- Test search(category=BJT_NPN)
- Test add_custom()
- Test library_id format validation

#### Week 3: Domain Updates

**Day 1-2: Update entities.py**
- Mở `domains/circuits/entities.py`
- Tìm class `Component`
- Thêm field `library_id: Optional[str] = None`
- Update `__post_init__()`:
  ```python
  def __post_init__(self):
      # Existing validations...
      
      # Validate library_id format
      if self.library_id:
          if ':' not in self.library_id:
              raise ValueError(f"Invalid library_id format: {self.library_id}. Expected 'Library:Symbol'")
  ```

**Day 3: Integrate SymbolLibrary**
- Update `Component` class để validate library_id tồn tại
- Optional: Add method `get_symbol_definition()` in Component

**Day 4-5: Integration tests**
- Test Component với library_id
- Test ComponentLibrary + SymbolLibrary integration
- Test end-to-end: ComponentSpec → Component → SymbolDefinition

**Files updated:**
- ✅ `app/domains/circuits/entities.py`
- ✅ `app/domains/circuits/component_library.py` (created)
- ✅ `tests/domain/test_component_library.py` (created)

**Deliverable**:
- ✅ ComponentLibrary với 20-30 models
- ✅ Component.library_id field working
- ✅ Validation passing
- ✅ Tests passing

---

### PHASE 3: Serializer Refactoring (Week 3-4) ⭐ CRITICAL

**Mục tiêu**: Serializer nhúng symbol từ KiCad, không còn tự vẽ

#### Week 3 (cont'd) - Day 6-7: Analyze current serializer

**Day 6: Study kicad_sch_serializer.py**
- Đọc hiểu code hiện tại
- Identify methods tự vẽ symbol (rectangles, arcs, pins)
- Document current flow

**Day 7: Design new flow**
- Design `_build_lib_symbols()` method
- Design updated `_serialize_symbol()` method
- Plan refactoring steps

#### Week 4: Implement refactoring

**Day 1-3: Implement _build_lib_symbols()**
```python
def _build_lib_symbols(self, circuit: Circuit) -> list[str]:
    """Build lib_symbols section from circuit components
    
    Args:
        circuit: Circuit with components having library_id
        
    Returns:
        List of S-expression strings for lib_symbols
    """
    # Step 1: Collect unique library_ids
    library_ids = set()
    for component in circuit.components.values():
        if component.library_id:
            library_ids.add(component.library_id)
    
    # Step 2: Lookup symbols from SymbolLibrary
    lib_symbols_lines = ['  (lib_symbols']
    
    for library_id in sorted(library_ids):
        symbol_def = self.symbol_library.get_symbol(library_id)
        if symbol_def:
            # Embed raw S-expression from symbol
            lib_symbols_lines.append(f'    {symbol_def.raw_sexp}')
    
    lib_symbols_lines.append('  )')
    
    return lib_symbols_lines
```

**Day 4: Update serialize() method**
```python
def serialize(self, ir: CircuitIR, placements, wires, junctions) -> str:
    circuit = ir.circuit
    lines = []
    
    # Header
    lines.extend(self._build_header(circuit))
    
    # ⭐ NEW: lib_symbols section
    lines.extend(self._build_lib_symbols(circuit))
    lines.append("")
    
    # Component instances (existing)
    for comp_id, component in circuit.components.items():
        pos = placements.get(comp_id, (50.0, 50.0))
        symbol_lines = self._build_symbol_instance(comp_id, component, pos[0], pos[1])
        lines.extend(symbol_lines)
    
    # ... rest of serialization
    
    return "\n".join(lines)
```

**Day 5: Update _serialize_symbol() to reference library_id**
```python
def _build_symbol_instance(self, comp_id: str, component: Component, x: float, y: float) -> list[str]:
    """Build symbol instance (NOT definition)
    
    Now references library_id instead of drawing
    """
    ref = component.parameters.get("reference", ParameterValue(comp_id))
    value = component.parameters.get("value", ParameterValue(""))
    uuid = self._generate_uuid()
    
    # Use library_id to reference symbol from lib_symbols
    lib_id = component.library_id or "Device:R"  # fallback
    
    lines = [
        f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0)',
        f'    (uuid "{uuid}")',
        '    (in_bom yes) (on_board yes)',
        f'    (property "Reference" "{ref.value}" ...)',
        f'    (property "Value" "{value.value}" ...)',
        '    (instances',
        f'      (project "" (path "/{self._root_uuid}" (reference "{ref.value}")))',
        '    )',
        '  )',
    ]
    
    return lines
```

**Files updated:**
- ✅ `app/infrastructure/exporters/kicad_sch_serializer.py`

**Deliverable**:
- ✅ `_build_lib_symbols()` implemented
- ✅ `serialize()` updated với lib_symbols section
- ✅ Symbol instances reference library_id
- ✅ NGỪNG tự vẽ symbol

---

### PHASE 4: Topology Modules (Week 4-5)

**Mục tiêu**: 10-15 topology modules hoạt động

#### Week 4 (cont'd): Base topology framework

**Day 6: Create base.py**
- Implement `TopologyConfig` base dataclass
- Implement `BaseTopologyBuilder` abstract class
- Define interface: `build()`, `validate_config()`

**Day 7: Create TopologyFactory**
- Implement registry pattern
- Method `create(topology_type, config)`
- Method `list_topologies()`

#### Week 5: Implement topologies

**Day 1: BJT Topologies**
- `bjt/common_emitter.py` - CEAmplifierBuilder
- `bjt/common_collector.py` - CCAmplifierBuilder  
- `bjt/common_base.py` - CBAmplifierBuilder

**Day 2: MOSFET Topologies**
- `mosfet/common_source.py` - CSAmplifierBuilder
- `mosfet/common_drain.py` - CDAmplifierBuilder
- `mosfet/common_gate.py` - CGAmplifierBuilder (optional)

**Day 3: OpAmp Topologies**
- `opamp/inverting.py` - InvertingOpAmpBuilder
- `opamp/non_inverting.py` - NonInvertingOpAmpBuilder
- `opamp/voltage_follower.py` - BufferBuilder

**Day 4: Oscillators**
- `oscillators/wien_bridge.py` - WienBridgeBuilder
- `oscillators/rc_phase_shift.py` - RCPhaseShiftBuilder
- `oscillators/astable_555.py` - Astable555Builder

**Day 5: Testing**
- Test each topology builder
- Validate circuits generated
- Export to .kicad_sch and validate with kicad-cli

**Files created:**
- ✅ `app/domains/circuits/topologies/base.py`
- ✅ `app/domains/circuits/topologies/__init__.py` (factory)
- ✅ `app/domains/circuits/topologies/bjt/*.py` (3 files)
- ✅ `app/domains/circuits/topologies/mosfet/*.py` (2-3 files)
- ✅ `app/domains/circuits/topologies/opamp/*.py` (3 files)
- ✅ `app/domains/circuits/topologies/oscillators/*.py` (3 files)
- ✅ `tests/domain/topologies/*.py` (test files)

**Deliverable**:
- ✅ 10-12 topology modules working
- ✅ Factory pattern implemented
- ✅ All topologies generate valid circuits
- ✅ kicad-cli validation passing

---

### PHASE 5: Application Layer DTOs + Use Cases (Week 5-6)

(Content continues with existing plan from original file...)

**Deliverable**:
- ✅ DTOs V2 complete
- ✅ Use cases updated
- ✅ API ready for V2

---

### PHASE 6-10: (Following original timeline)

- Week 6-7: API V2 Endpoints
- Week 7-8: Database + Persistence  
- Week 8-9: Frontend Refactoring
- Week 9-10: Testing + Validation
- Week 10-11: Documentation + Deployment

---

## 📊 SUMMARY & SUCCESS METRICS

## 📊 SUMMARY & SUCCESS METRICS

### Files Summary

#### Files to Update: 16
- ✅ **Python Backend** (10 files):
  - `template_builder.py` - Refactored to use ComponentLibrary
  - `entities.py` - Added library_id field
  - `kicad_sch_serializer.py` - Embed symbols from KiCad
  - `dtos.py` - V2 DTOs added
  - `generate_circuit.py` - Updated use case
  - `prompt_analyzer.py` - V2 analysis
  - `circuits.py` (routes) - V2 endpoints
  - `kicad_sch_exporter.py` - Inject ComponentLibrary
  - `main.py` - Mount V2 routers
  - `config.py` - Add resource paths

- ✅ **Frontend** (2 files):
  - `demo.html` - Tách CSS/JS
  - `viewer.html` - Tách CSS/JS

- ⚠️ **Deprecate** (4 files):
  - `api/endpoints.py` → rename to `routes_v1_compat.py`

#### Files to Create: 40+

- ✅ **Resources** (7 files):
  - `resources/kicad/symbols/*.kicad_sym` (6 files)
  - `resources/kicad/kicad_lib_manifest.json`

- ✅ **Domain** (15+ files):
  - `component_library.py`
  - `topologies/base.py`
  - `topologies/__init__.py` (factory)
  - `topologies/bjt/*.py` (3 files)
  - `topologies/mosfet/*.py` (3 files)
  - `topologies/opamp/*.py` (3 files)
  - `topologies/oscillators/*.py` (3 files)

- ✅ **Infrastructure** (5 files):
  - `kicad/symbol_parser.py`
  - `kicad/symbol_library.py`
  - `kicad/__init__.py`
  - `db/repositories/component_library_repository.py`
  - `db/repositories/__init__.py` (update)

- ✅ **Application** (3 files):
  - `ai/circuit_generation_agent.py`
  - `ai/__init__.py`
  - Routes V2 files

- ✅ **Database** (3 files):
  - `migrations/001_initial_schema.sql`
  - `migrations/002_add_component_library.sql`
  - `migrations/003_seed_component_library.sql`

- ✅ **Frontend** (8 files):
  - `static/css/demo.css`
  - `static/css/viewer.css`
  - `static/js/demo.js` + modules (4 files)
  - `static/js/viewer.js` + modules (4 files)

- ✅ **Tests** (10+ files):
  - `tests/infrastructure/kicad/*.py` (3 files)
  - `tests/domain/test_component_library.py`
  - `tests/domain/topologies/*.py` (6 files)

- ✅ **Documentation** (6 files):
  - `docs/api/v2_endpoints.md`
  - `docs/api/component_library_api.md`
  - `docs/api/migration_guide.md`
  - `docs/developer/symbol_sourcing.md`
  - `docs/developer/adding_components.md`
  - `docs/developer/render_debugging.md`

---

### Success Metrics

#### Phase 1-2 (Week 1-3): Foundation ⭐
- ✅ 6 KiCad symbol libraries vendored
- ✅ SymbolParser parses 29+ symbols
- ✅ ComponentLibrary contains 20-30 models
- ✅ Component.library_id validation working
- ✅ 100% unit tests passing

#### Phase 3 (Week 3-4): Serializer ⭐
- ✅ lib_symbols section generated correctly
- ✅ Symbol instances reference library_id
- ✅ 0% self-drawn symbols (all from KiCad)
- ✅ kicad-cli validation passing
- ✅ KiCanvas renders correctly

#### Phase 4 (Week 4-5): Topologies
- ✅ 10-12 topology modules implemented
- ✅ TopologyFactory working
- ✅ All topologies generate valid circuits
- ✅ End-to-end tests passing

#### Phase 5-6 (Week 5-8): Application & API
- ✅ API V2 endpoints working
- ✅ DTOs V2 validated
- ✅ Backward compatibility with V1
- ✅ Swagger documentation complete

#### Phase 7-8 (Week 7-9): Database & Frontend
- ✅ Database migrations applied
- ✅ Component catalog seeded
- ✅ Frontend modularized (CSS/JS separated)
- ✅ API V2 integration complete

#### Phase 9-10 (Week 9-11): Testing & Deployment
- ✅ Test coverage >70%
- ✅ E2E tests for all topologies
- ✅ Performance: 100+ circuits/min
- ✅ Production deployment successful

---

### Timeline Summary

**Total Duration**: 11 weeks (~2.75 months)

**Critical Path**:
1. Week 0: Preparation
2. Week 1-2: **Vendor Symbols + Parser** ⭐ CRITICAL
3. Week 2-3: Component Library + Domain
4. Week 3-4: **Serializer Refactoring** ⭐ CRITICAL
5. Week 4-5: **Topology Modules** ⭐ IMPORTANT
6. Week 5-6: Application DTOs
7. Week 6-7: API V2
8. Week 7-8: Database
9. Week 8-9: Frontend
10. Week 9-10: Testing
11. Week 10-11: Deployment

**Fastest Path** (if resources available): 8 weeks
**Safest Path** (with buffer): 12-13 weeks

---

### Risk Mitigation

#### High Risk Items ⚠️
1. **Symbol parsing complexity**
   - Mitigation: Start with simple symbols (R, C), expand gradually
   - Fallback: Use pre-parsed symbol cache

2. **KiCanvas rendering differences**
   - Mitigation: Extensive testing with kicad-cli validation
   - Fallback: Always provide SVG fallback

3. **Topology module complexity**
   - Mitigation: Start with MVP (5 topologies), expand later
   - Fallback: Keep legacy template_builder as backup

4. **Database migration issues**
   - Mitigation: Test migrations on staging first
   - Fallback: Keep V1 schema, run dual-schema mode

#### Medium Risk Items
- Frontend refactoring breaking existing UI
- API V2 performance issues
- Test coverage not reaching 70%

---

### Next Steps - BƯỚC ĐẦU TIÊN

**IMMEDIATE ACTION** (Next 1 hour):
1. ✅ Create git branch: `git checkout -b feature/vendor-kicad-symbols`
2. ✅ Create folder structure (see Phase 0)
3. ✅ Add `sexpdata==1.0.0` to requirements.txt
4. ✅ Install dependency: `pip install sexpdata`

**THIS WEEK** (Week 1):
1. Clone kicad-symbols repo
2. Copy 6 symbol files to resources/
3. Create kicad_lib_manifest.json
4. Verify symbols with text editor

**NEXT WEEK** (Week 2):
1. Implement symbol_parser.py
2. Implement symbol_library.py
3. Write unit tests
4. Validate parsing works

**VALIDATION CRITERIA**:
```bash
# Success = All these commands pass
pytest tests/infrastructure/kicad/ -v
python -m app.infrastructure.kicad.symbol_library  # Test manual load
kicad-cli version  # Verify CLI available
```

---

### Contact & Support

**Documentation**:
- Main roadmap: `docs/domain/UPGRADE_ROADMAP_DETAILED.md`
- Symbol sourcing: `docs/developer/symbol_sourcing.md` (to be created)
- API V2: `docs/api/v2_endpoints.md` (to be created)

**Git Workflow**:
```bash
# Feature branches
feature/vendor-kicad-symbols (Week 1-2)
feature/component-library (Week 2-3)
feature/serializer-refactor (Week 3-4)
feature/topology-modules (Week 4-5)
feature/api-v2 (Week 5-7)
feature/frontend-refactor (Week 8-9)

# Merge to main after each phase passes tests
```

**Testing Strategy**:
- Unit tests: After each file created
- Integration tests: After each phase
- E2E tests: Week 9-10
- Performance tests: Week 10

---

**Version:** 2.0  
**Last Updated:** January 25, 2026  
**Status:** Ready for Implementation  
**Author:** AI Assistant (Claude Sonnet 4.5)  
**Review Status:** ✅ Approved for production roadmap

---

## 🚀 BẮT ĐẦU NGAY

Sẵn sàng bắt đầu Phase 0 (Chuẩn bị) và Phase 1 (Vendor KiCad Symbols)?

Chạy lệnh:
```bash
# Create branch
git checkout -b feature/vendor-kicad-symbols

# Create folders
mkdir -p apps/api/resources/kicad/symbols
mkdir -p apps/api/app/infrastructure/kicad
mkdir -p apps/api/tests/infrastructure/kicad

# Install dependency
echo "sexpdata==1.0.0" >> apps/api/requirements.txt
pip install sexpdata

# Verify
ls -la apps/api/resources/kicad/symbols
```

Sau khi hoàn thành, hệ thống sẽ đạt **70-80% production-ready** với khả năng:
- ✅ Render đẹp giống hệt KiCad
- ✅ 10-15 topology amplifier + oscillator
- ✅ Component catalog 20-30 models
- ✅ API V2 professional
- ✅ Test coverage >70%
- ✅ Documentation đầy đủ

**→ Không còn demo, trở thành hệ thống thật!**
