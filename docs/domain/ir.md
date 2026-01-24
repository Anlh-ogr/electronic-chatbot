
# Intermediate Representation (IR) trong Circuits Domain

Tài liệu này mô tả file `ir.py` trong domain circuits của dự án electronic-chatbot. File này định nghĩa lớp trung gian (Intermediate Representation - IR) và bộ chuyển đổi/serialize dữ liệu mạch điện tử, giúp tách biệt hoàn toàn giữa domain logic (entities) và các tầng lưu trữ, truyền tải, API, hoặc AI.

---

## Chức năng

- **Định nghĩa lớp IR:**  
   - `CircuitIR` là lớp bất biến (immutable) chứa entity `Circuit`, snapshot ý định (`intent_snapshot`) và metadata (`meta`).  
   - Đảm bảo dữ liệu mạch điện được đóng gói an toàn, không thể bị sửa đổi ngoài ý muốn từ bên ngoài.

- **Chuyển đổi giữa Entity và IR:**  
   - `CircuitIRSerializer` cung cấp các hàm chuyển đổi hai chiều giữa entity (`Circuit`) và IR (dạng dict/json), bao gồm cả xác thực schema cơ bản.

- **Serialization/Deserialization:**  
   - Hỗ trợ chuyển đổi mạch sang dạng dictionary (hoặc json) để lưu trữ/truyền tải, và ngược lại.

- **Schema Validation:**  
   - Kiểm tra cấu trúc dữ liệu IR trước khi deserialize, đảm bảo không bị lỗi khi truyền qua các tầng khác hoặc lưu trữ.

- **Roundtrip Test:**  
   - Hỗ trợ kiểm tra tính toàn vẹn dữ liệu khi serialize rồi deserialize lại (không mất thông tin).

---

## Mục tiêu

- **Tách biệt entity và storage/transmission:**  
   - Entity là "truth in code", IR là "truth for storage/transmission".  
   - Bảo vệ domain logic khỏi các thay đổi về lưu trữ hoặc giao tiếp.

- **Đảm bảo tính bất biến:**  
   - Dữ liệu IR không thể bị sửa đổi ngoài ý muốn, sử dụng dataclass(frozen=True) và MappingProxyType.

- **Chuẩn hóa dữ liệu truyền tải:**  
   - Đảm bảo dữ liệu khi truyền qua API, lưu DB hoặc gửi sang AI agent luôn đúng schema, dễ kiểm soát và debug.

- **Hỗ trợ kiểm thử và phát triển:**  
   - Cho phép kiểm tra roundtrip (entity → IR → entity) để phát hiện lỗi serialize/deserialize.

---

## Cấu trúc

1. **CircuitIR:**  
    - Chứa entity `Circuit`, intent_snapshot (dict), meta (dict: version, schema_version, circuit_name, created_at, ...).
    - Bất biến, public chỉ read-only (dùng MappingProxyType).

2. **CircuitIRSerializer:**  
    - `to_dict()`: Chuyển IR thành dict (json-serializable).
    - `from_dict()`: Chuyển dict thành IR (có validate schema).
    - `serialize()`: Circuit → dict IR.
    - `deserialize()`: dict IR → Circuit.
    - `validate_schema()`: Kiểm tra schema IR (không kiểm tra logic điện).
    - `build_ir()`: Tạo IR từ entity với meta tự động.
    - `roundtrip_test()`: Kiểm tra serialize-deserialize không mất dữ liệu.

3. **Schema Validation:**  
    - Kiểm tra các trường bắt buộc (meta, components, nets, ports, constraints).
    - Kiểm tra kiểu dữ liệu, enum, cấu trúc lồng nhau.
    - Báo lỗi chi tiết nếu thiếu trường, sai kiểu, hoặc enum không hợp lệ.

---

## Vai trò

- **Cầu nối giữa domain và storage/API:**  
   - Đảm bảo dữ liệu domain khi lưu trữ hoặc truyền tải luôn đúng định dạng, không bị phụ thuộc vào chi tiết implementation của entity.

- **Bảo vệ domain khỏi lỗi truyền tải:**  
   - Nếu dữ liệu IR sai schema, sẽ báo lỗi rõ ràng, tránh bug khó debug ở tầng dưới.

- **Hỗ trợ kiểm thử tự động:**  
   - Dễ dàng kiểm tra tính toàn vẹn dữ liệu khi serialize/deserialize.

- **Tiện lợi cho frontend/API/DB:**  
   - Dữ liệu IR đã chuẩn hóa, dễ dàng sử dụng ở các tầng khác nhau mà không cần hiểu chi tiết domain logic.

---

## Kiến trúc & Giải thích lựa chọn

- **Vì sao cần IR?**  
   - Entity domain tập trung bảo vệ logic nghiệp vụ, còn IR giúp chuẩn hóa dữ liệu cho lưu trữ, truyền tải, API, AI, ...  
   - IR giúp dễ dàng thay đổi schema lưu trữ mà không ảnh hưởng đến domain logic.

- **Bất biến tuyệt đối:**  
   - Sử dụng dataclass(frozen=True) và MappingProxyType để bảo vệ dữ liệu khỏi sửa đổi ngoài ý muốn.

- **Schema validation chi tiết:**  
   - Kiểm tra từng trường, từng enum, từng kiểu dữ liệu, giúp phát hiện lỗi sớm và debug dễ dàng.

- **Roundtrip test:**  
   - Đảm bảo serialize-deserialize không làm mất dữ liệu, giúp phát hiện bug serialization.

- **Tách biệt concerns:**  
   - IR không chứa logic nghiệp vụ, chỉ là lớp trung gian cho lưu trữ/truyền tải.

---

## Review Tổng Quan

**Điểm mạnh:**
- Thiết kế bất biến, bảo vệ dữ liệu an toàn.
- Chuẩn hóa dữ liệu truyền tải, dễ dùng cho API, DB, AI.
- Validation schema chi tiết, báo lỗi rõ ràng.
- Dễ kiểm thử, dễ debug, hỗ trợ phát triển nhanh.
- Tách biệt hoàn toàn với entity logic, dễ bảo trì.

**Điểm cần cải thiện:**
- Validation chỉ kiểm tra schema, không kiểm tra logic điện (nên kết hợp với entity validation nếu cần).
- Có thể mở rộng thêm các schema version, backward compatibility nếu thay đổi lớn.

---

## Ví dụ sử dụng

```python
# Serialize một Circuit entity thành dict IR
ir_dict = CircuitIRSerializer.serialize(circuit)

# Deserialize từ dict IR thành Circuit entity
circuit = CircuitIRSerializer.deserialize(ir_dict)

# Kiểm tra roundtrip
assert CircuitIRSerializer.roundtrip_test(circuit)
```

---

File `ir.py` là lớp trung gian quan trọng giúp hệ thống tách biệt domain logic với lưu trữ/truyền tải, bảo vệ tính toàn vẹn dữ liệu và hỗ trợ phát triển, kiểm thử hiệu quả.
