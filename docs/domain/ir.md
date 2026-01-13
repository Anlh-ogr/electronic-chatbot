# Tài liệu IR (Intermediate Representation) cho Circuits Domain

Tài liệu này mô tả file `ir.py` trong domain circuits của dự án electronic-chatbot. File này định nghĩa lớp trung gian (Intermediate Representation - IR) dùng để lưu trữ, truyền tải hoặc serialize mạch điện giữa các tầng (layer) khác nhau, tách biệt hoàn toàn với entity domain logic.

## Chức năng
- **Định nghĩa lớp IR:** `CircuitIR` là lớp bất biến (immutable) chứa dữ liệu mạch điện (`Circuit` entity), snapshot ý định (intent_snapshot) và metadata (meta).
- **Chuyển đổi giữa Entity và IR:** `CircuitIRSerializer` cung cấp các hàm chuyển đổi hai chiều giữa entity (`Circuit`) và IR (dạng dict/json), bao gồm cả xác thực schema cơ bản.
- **Serialization/Deserialization:** Hỗ trợ chuyển đổi mạch sang dạng dictionary (hoặc json) để lưu trữ/truyền tải, và ngược lại.
- **Schema Validation:** Kiểm tra cấu trúc dữ liệu IR trước khi deserialize, đảm bảo không bị lỗi khi truyền qua các tầng khác hoặc lưu trữ.
- **Roundtrip Test:** Hỗ trợ kiểm tra tính toàn vẹn dữ liệu khi serialize rồi deserialize lại (không mất thông tin).

## Mục tiêu
- **Tách biệt entity và storage/transmission:** Entity là "truth in code", IR là "truth for storage/transmission". Điều này giúp bảo vệ domain logic khỏi các thay đổi về lưu trữ hoặc giao tiếp.
- **Đảm bảo tính bất biến:** Dữ liệu IR không thể bị sửa đổi ngoài ý muốn.
- **Chuẩn hóa dữ liệu truyền tải:** Đảm bảo dữ liệu khi truyền qua API, lưu DB hoặc gửi sang AI agent luôn đúng schema, dễ kiểm soát và debug.
- **Hỗ trợ kiểm thử và phát triển:** Cho phép kiểm tra roundtrip (entity → IR → entity) để phát hiện lỗi serialize/deserialize.

## Cấu trúc
1. **CircuitIR:**
   - Chứa entity `Circuit`, intent_snapshot (dict), meta (dict, ví dụ: version, schema_version, circuit_name, created_at).
   - Bất biến, public chỉ read-only.
2. **CircuitIRSerializer:**
   - `to_dict()`: Chuyển IR thành dict (json-serializable).
   - `from_dict()`: Chuyển dict thành IR (có validate schema).
   - `serialize()`: Circuit → dict IR.
   - `deserialize()`: dict IR → Circuit.
   - `validate_schema()`: Kiểm tra schema IR (không kiểm tra logic điện).
   - `build_ir()`: Tạo IR từ entity với meta tự động.
   - `roundtrip_test()`: Kiểm tra serialize-deserialize không mất dữ liệu.

## Vai trò
- **Cầu nối giữa domain và storage/API:** Đảm bảo dữ liệu domain khi lưu trữ hoặc truyền tải luôn đúng định dạng, không bị phụ thuộc vào chi tiết implementation của entity.
- **Bảo vệ domain khỏi lỗi truyền tải:** Nếu dữ liệu IR sai schema, sẽ báo lỗi rõ ràng, tránh bug khó debug ở tầng dưới.
- **Hỗ trợ kiểm thử tự động:** Dễ dàng kiểm tra tính toàn vẹn dữ liệu khi serialize/deserialize.
- **Tiện lợi cho frontend/API/DB:** Dữ liệu IR đã chuẩn hóa, dễ dàng sử dụng ở các tầng khác nhau mà không cần hiểu chi tiết domain logic.

## Tổng kết
File `ir.py` là lớp trung gian quan trọng giúp hệ thống tách biệt domain logic với lưu trữ/truyền tải, bảo vệ tính toàn vẹn dữ liệu và hỗ trợ phát triển, kiểm thử hiệu quả.
