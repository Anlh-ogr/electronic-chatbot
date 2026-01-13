# Tài liệu Rules Engine cho Circuits Domain

Tài liệu này mô tả file `rules.py` trong domain circuits của dự án electronic-chatbot. File này định nghĩa hệ thống kiểm tra quy tắc (rules engine) cho mạch điện, giúp phát hiện lỗi thiết kế, cảnh báo và đảm bảo mạch hợp lệ trước khi xuất bản, mô phỏng hoặc sản xuất.

## Chức năng
- **Định nghĩa các quy tắc kiểm tra (rules):** Mỗi rule là một class kế thừa từ `CircuitRule`, kiểm tra một khía cạnh của mạch (tham số linh kiện, kết nối, topology, constraint, v.v.).
- **Phát hiện lỗi và cảnh báo:** Rules trả về danh sách `RuleViolation` với thông tin chi tiết về lỗi, mức độ nghiêm trọng (ERROR, WARNING, INFO), vị trí lỗi (component, net, port, constraint).
- **Rules Engine tổng hợp:** `CircuitRulesEngine` chạy toàn bộ rules trên một mạch, gom kết quả, sắp xếp theo mức độ nghiêm trọng, và hỗ trợ summary.
- **Hỗ trợ mở rộng:** Có thể đăng ký thêm rules mới qua `RuleRegistry` cho các phase sau.
- **Validation helpers:** Hàm tiện ích validate mạch, trả về kết quả chi tiết hoặc summary cho các tầng khác sử dụng.

## Mục tiêu
- **Tách biệt business logic khỏi entity:** Không nhồi nhét logic kiểm tra vào entity, mà tách ra thành rules độc lập, dễ mở rộng và bảo trì.
- **Phát hiện lỗi sớm:** Kiểm tra mạch ngay sau khi generate (từ AI, template, user input), phát hiện lỗi như thiếu nguồn, trùng pin, topology sai, constraint bất hợp lý, v.v.
- **Chuẩn hóa kiểm tra:** Mỗi rule rõ ràng, có thể test độc lập, dễ trace lỗi.
- **Hỗ trợ phát triển và kiểm thử:** Dễ dàng thêm rule mới, test từng rule, và tổng hợp kết quả cho UI/API.

## Cấu trúc
1. **RuleViolation:**
   - Thông tin vi phạm: rule_name, message, severity, vị trí lỗi (component_id, net_name, ...), details.
2. **CircuitRule (base class):**
   - Mỗi rule kế thừa, cài đặt hàm `validate(circuit)` trả về list RuleViolation.
3. **Các rule cụ thể:**
   - `ComponentParameterRule`: Kiểm tra tham số bắt buộc của linh kiện.
   - `PinConnectionRule`: Kiểm tra pin phải được kết nối đúng.
   - `GroundReferenceRule`: Mạch phải có ground.
   - `OpAmpPowerRule`: OpAmp phải có nguồn.
   - `BJTBiasingRule`: BJT phải có phân cực đúng.
   - `NetSingleConnectionRule`: Net chỉ có 1 connection là nghi ngờ.
   - `ConstraintFeasibilityRule`: Constraint có giá trị hợp lý.
   - `PortDirectionRule`: Hướng port hợp lý.
   - `ComponentUniqueIdRule`: ID linh kiện không trùng.
   - `CircuitTopologyRule`: Topology hợp lý với constraint.
4. **CircuitRulesEngine:**
   - Chạy toàn bộ rules, gom kết quả, summary, validate_and_throw (ném exception nếu có lỗi ERROR).
5. **Helpers:**
   - `validate_circuit`, `validate_circuit_with_summary`: Hàm tiện ích cho tầng trên.
   - `RuleRegistry`: Đăng ký rule custom.
   - `create_test_circuit`: Tạo mạch test mẫu.

## Vai trò
- **Bảo vệ chất lượng mạch:** Đảm bảo mạch hợp lệ trước khi xuất bản, mô phỏng, hoặc sản xuất.
- **Cầu nối giữa domain và application:** Cho phép tầng trên kiểm tra mạch dễ dàng, nhận kết quả chi tiết hoặc summary.
- **Hỗ trợ mở rộng:** Dễ dàng thêm rule mới cho các phase tiếp theo.
- **Tăng tính maintainable:** Tách biệt logic kiểm tra, dễ test, dễ trace lỗi, không làm rối entity.

## Tổng kết
File `rules.py` là trung tâm kiểm tra chất lượng mạch điện, giúp phát hiện lỗi sớm, bảo vệ domain, và hỗ trợ phát triển mở rộng, kiểm thử hiệu quả.
