# Electronic Chatbot API - MVP Guide

## 🎯 Mục tiêu MVP

MVP này demo end-to-end flow:
1. **Generate**: Tạo mạch từ template (BJT amplifier, OpAmp)
2. **Validate**: Kiểm tra mạch theo domain rules
3. **Export**: Xuất file `.kicad_sch` thực tế
4. **Download**: Tải file về để mở trong KiCad

## 🏗️ Kiến trúc đã triển khai

```
app/
├── domains/circuits/              ✅ Domain layer (entities, rules, IR, templates)
├── application/circuits/          ✅ Application layer
│   ├── ports.py                   ✅ Interfaces (Protocols)
│   ├── dtos.py                    ✅ Data Transfer Objects
│   ├── errors.py                  ✅ Application errors
│   └── use_cases/                 ✅ Business logic
│       ├── generate_circuit.py    ✅ Generate from template
│       ├── validate_circuit.py    ✅ Validate with rules
│       └── export_kicad_sch.py    ✅ Export to KiCad
├── infrastructure/                ✅ Infrastructure adapters
│   ├── persistence/
│   │   └── circuits_repo_memory.py ✅ In-memory repository
│   ├── exporters/
│   │   └── kicad_sch_exporter.py   ✅ KiCad exporter
│   └── validation/
│       └── validation_service.py   ✅ Rules engine adapter
├── interfaces/http/               ✅ HTTP interface (FastAPI)
│   ├── deps.py                    ✅ Dependency injection
│   └── routes/circuits.py         ✅ REST endpoints
└── main.py                        ✅ FastAPI app
```

## 🚀 Chạy API

### 1. Kích hoạt môi trường ảo

```powershell
# Từ thư mục apps/api
.\.venv\Scripts\Activate.ps1
```

### 2. Cài đặt dependencies (nếu cần)

```powershell
pip install -r requirements.txt
```

### 3. Chạy server

```powershell
# Development mode với hot reload
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Hoặc chạy trực tiếp
python app/main.py
```

### 4. Truy cập API

- **API Docs (Swagger)**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Root**: http://localhost:8000/
- **Health Check**: http://localhost:8000/health

## 📡 API Endpoints

### 1. Generate Circuit from Template

```http
POST /api/circuits/generate
Content-Type: application/json

{
  "template_name": "bjt_common_emitter",
  "name": "My BJT Amplifier",
  "description": "Common emitter amplifier for testing",
  "author": "Demo User",
  "parameters": {
    "vcc": 12.0,
    "rc": 4700,
    "re": 1000,
    "r1": 47000,
    "r2": 10000,
    "beta": 100
  },
  "tags": ["bjt", "amplifier", "test"]
}
```

**Response**: `CircuitResponse` với circuit ID

### 2. Validate Circuit

```http
POST /api/circuits/validate/{circuit_id}
```

**Response**: `CircuitValidationResponse` với violations và suggestions

### 3. Export to KiCad

```http
POST /api/circuits/export/{circuit_id}/kicad
```

**Response**: `ExportCircuitResponse` với file path và download URL

### 4. Download Exported File

```http
GET /artifacts/exports/{filename}
```

## 🧪 Test bằng curl

### 1. Generate circuit

```powershell
$body = @{
    template_name = "bjt_common_emitter"
    name = "Test BJT CE"
    description = "Testing circuit generation"
    author = "Test"
    parameters = @{
        vcc = 12.0
        rc = 4700
        re = 1000
        r1 = 47000
        r2 = 10000
        beta = 100
    }
    tags = @("test", "bjt")
} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "http://localhost:8000/api/circuits/generate" -Method POST -Body $body -ContentType "application/json"
$circuitId = $response.id
Write-Host "Circuit ID: $circuitId"
```

### 2. Validate circuit

```powershell
$validation = Invoke-RestMethod -Uri "http://localhost:8000/api/circuits/validate/$circuitId" -Method POST
$validation | ConvertTo-Json -Depth 10
```

### 3. Export to KiCad

```powershell
$export = Invoke-RestMethod -Uri "http://localhost:8000/api/circuits/export/$circuitId/kicad" -Method POST
Write-Host "File path: $($export.file_path)"
Write-Host "Download URL: $($export.download_url)"
```

### 4. Download file

```powershell
Invoke-WebRequest -Uri "http://localhost:8000$($export.download_url)" -OutFile "my_circuit.kicad_sch"
```

## 📋 Templates có sẵn

| Template Name | Description | Required Parameters |
|--------------|-------------|---------------------|
| `bjt_common_emitter` | BJT Common Emitter | vcc, rc, re, r1, r2, beta |
| `bjt_common_collector` | BJT Common Collector | vcc, rc, re, r1, r2, beta |
| `bjt_common_base` | BJT Common Base | vcc, rc, re, r1, r2, beta |
| `opamp_inverting` | OpAmp Inverting | vcc, vee, rf, rin |
| `opamp_non_inverting` | OpAmp Non-Inverting | vcc, vee, rf, rin |
| `opamp_differential` | OpAmp Differential | vcc, vee, rf, rin |

## 🐛 Troubleshooting

### ModuleNotFoundError

```powershell
# Đảm bảo đang ở đúng thư mục và venv đã kích hoạt
cd D:\Work\thesis\electronic-chatbot\apps\api
.\.venv\Scripts\Activate.ps1
```

### Port đã được sử dụng

```powershell
# Thay đổi port
uvicorn app.main:app --reload --port 8001
```

### Import errors

```powershell
# Kiểm tra PYTHONPATH (nếu cần)
$env:PYTHONPATH = "D:\Work\thesis\electronic-chatbot\apps\api"
```

## 🎨 Tích hợp Frontend (Next Steps)

Từ frontend (apps/web), gọi API:

```javascript
// Generate circuit
const response = await fetch('http://localhost:8000/api/circuits/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    template_name: 'bjt_common_emitter',
    name: 'My Circuit',
    parameters: { /* ... */ }
  })
});

const circuit = await response.json();
console.log('Circuit ID:', circuit.id);

// Export to KiCad
const exportResponse = await fetch(
  `http://localhost:8000/api/circuits/export/${circuit.id}/kicad`,
  { method: 'POST' }
);

const exportData = await exportResponse.json();

// Download file
window.location.href = `http://localhost:8000${exportData.download_url}`;
```

## 📊 Coverage & Tests

Run tests cho application layer:

```powershell
pytest tests/application/ -v --cov=app.application.circuits --cov-report=html
```

Coverage hiện tại:
- **dtos.py**: 95%
- **ports.py**: 100%
- **Total**: 96%

## 🔄 Next Steps

1. ✅ **Use Cases** - Hoàn thành
2. ✅ **Adapters** - Hoàn thành (in-memory, KiCad exporter)
3. ✅ **HTTP Interface** - Hoàn thành (FastAPI routes)
4. 🚧 **Frontend Integration** - Cần làm
5. 🚧 **Database Persistence** - Optional (hiện tại dùng in-memory)
6. 🚧 **Authentication** - Optional (cho production)

## 📝 Notes

- Repository hiện tại là **in-memory** - data mất khi restart server
- Để persist data, implement `circuits_repo_pg.py` với PostgreSQL
- KiCad exporter tạo file `.kicad_sch` cơ bản, có thể mở trong KiCad 7.x
- Validation sử dụng domain rules engine với 10 built-in rules
