# Tài liệu Template Builder cho Circuits Domain

Tài liệu này mô tả file `template_builder.py` trong domain circuits của dự án electronic-chatbot. File này định nghĩa các builder và factory để sinh tự động các mạch khuếch đại (amplifier) dựa trên tham số đầu vào, giúp AI agent hoặc user tạo mạch nhanh, đúng topology và giá trị linh kiện.

## Chức năng
- **Định nghĩa cấu hình tham số (Config):** Các dataclass như `BJTAmplifierConfig`, `OpAmpAmplifierConfig` mô tả đầy đủ các tham số cần thiết để sinh mạch (topology, gain, VCC, model, ...).
- **Tính toán giá trị linh kiện:** Các class calculator (`BJTComponentCalculator`, `OpAmpComponentCalculator`) tự động tính toán giá trị resistor, capacitor, ... từ tham số đầu vào (theo công thức chuẩn).
- **Builder sinh mạch tự động:**
  - `BJTAmplifierBuilder`, `OpAmpAmplifierBuilder` nhận config, tự động sinh đúng số lượng linh kiện, kết nối, port, constraint cho từng topology (CE, CC, CB, inverting, non-inverting, differential).
  - Tự động tính toán, gán giá trị linh kiện, sinh netlist phù hợp.
- **Factory API đơn giản:** `AmplifierFactory` cung cấp hàm tạo mạch nhanh cho AI/user, chỉ cần truyền topology, gain, vcc, ...
- **Dễ mở rộng:** Có thể thêm topology mới, loại mạch mới mà không ảnh hưởng code cũ.

## Mục tiêu
- **Tự động hóa sinh mạch:** Giúp AI agent hoặc user tạo mạch nhanh, đúng topology, đúng giá trị linh kiện, giảm lỗi thủ công.
- **Chuẩn hóa cấu trúc mạch:** Đảm bảo mạch sinh ra luôn hợp lệ, đúng chuẩn, dễ kiểm tra bằng rules engine.
- **Tách biệt logic sinh mạch:** Builder/factory tách biệt hoàn toàn với entity, dễ bảo trì, mở rộng.
- **Hỗ trợ AI agent:** Cho phép AI customize tham số, sinh nhiều loại mạch khác nhau chỉ với 1-2 dòng code.

## Cấu trúc
1. **Config dataclass:**
   - `BJTAmplifierConfig`, `OpAmpAmplifierConfig`: Định nghĩa tham số cho từng loại mạch.
2. **Component Calculator:**
   - `BJTComponentCalculator`, `OpAmpComponentCalculator`: Tính toán giá trị resistor, capacitor, ...
3. **Builder:**
   - `BJTAmplifierBuilder`, `OpAmpAmplifierBuilder`: Nhận config, sinh mạch (components, nets, ports, constraints) cho từng topology.
4. **Factory:**
   - `AmplifierFactory`: API đơn giản cho AI/user tạo mạch nhanh.

## Vai trò
- **Tăng tốc phát triển:** Giúp AI agent, developer, hoặc user tạo mạch mẫu nhanh, đúng chuẩn, giảm lỗi.
- **Chuẩn hóa đầu vào cho rules engine:** Mạch sinh ra luôn hợp lệ, dễ kiểm tra, dễ debug.
- **Hỗ trợ mở rộng:** Dễ thêm topology mới, loại mạch mới, hoặc customize tham số.
- **Tách biệt concerns:** Logic sinh mạch tách khỏi entity, domain, giúp code maintainable, testable.

## Tổng kết
File `template_builder.py` là công cụ mạnh mẽ giúp tự động hóa sinh mạch khuếch đại, chuẩn hóa cấu trúc, hỗ trợ AI agent và tăng tốc phát triển hệ thống.