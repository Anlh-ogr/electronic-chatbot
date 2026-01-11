# Entities trong Circuits Domain

Tài liệu này mô tả file `entities.py` trong domain circuits của dự án electronic-chatbot. File này định nghĩa các thực thể (entities) cốt lõi đại diện cho mạch điện, tập trung vào logic domain thuần túy mà không lẫn lộn với AI, KiCad hoặc UI. Tất cả các lớp đều được thiết kế immutable (bất biến) để bảo vệ source of truth (nguồn sự thật).

Dưới đây là phân tích theo các khía cạnh yêu cầu: chức năng, mục tiêu, cấu trúc, vai trò và review tổng quan.

## Chức năng
File `entities.py` cung cấp các lớp và enum để mô hình hóa các thành phần cơ bản của mạch điện. Các chức năng chính bao gồm:
- **Định nghĩa loại linh kiện và hướng port:** Sử dụng enum (`ComponentType` và `PortDirection`) để liệt kê các loại linh kiện (như resistor, capacitor) và hướng port (input, output, power, ground), ngăn chặn lỗi typo và hỗ trợ auto-complete.
- **Mô hình hóa giá trị tham số và tham chiếu chân:** Value objects như `ParameterValue` chuẩn hóa tham số linh kiện (chỉ chấp nhận int, float, str với đơn vị tùy chọn), và `PinRef` tham chiếu đến chân của linh kiện trong kết nối.
- **Định nghĩa linh kiện, kết nối, port và ràng buộc:**
  - `Component`: Đại diện linh kiện với ID, loại, chân và tham số, kèm validation cơ bản (ví dụ: resistor phải có "resistance").
  - `Net`: Đại diện kết nối điện giữa các chân, với validation chống duplicate và kiểm tra tồn tại.
  - `Port`: Giao diện mạch với bên ngoài, liên kết với net và hướng.
  - `Constraint`: Ràng buộc kỹ thuật (như supply_voltage, target_gain) làm input cho rules engine.
- **Tập hợp toàn bộ mạch:** `Circuit` là aggregate root, chứa collections của components, nets, ports và constraints. Nó thực hiện validation invariants (kiểm tra tính nhất quán như net phải tồn tại, pin không thuộc nhiều net).
- Hỗ trợ serialization: Mỗi lớp có phương thức `to_dict()` để chuyển đổi sang dictionary, tiện cho lưu trữ hoặc truyền dữ liệu.
- Bảo vệ bất biến: Sử dụng `frozen=True` trong dataclass, `MappingProxyType` cho dictionary, và defensive copy để ngăn chặn sửa đổi từ bên ngoài.

## Mục tiêu
Mục tiêu chính của file này là xây dựng một domain model vững chắc theo nguyên tắc Domain-Driven Design (DDD), tập trung vào:
- **Bảo vệ invariants:** Đảm bảo tính nhất quán dữ liệu (ví dụ: pin không duplicate, tham số hợp lệ) để tránh lỗi logic ở các layer khác.
- **Tách biệt concerns:** Giữ domain thuần túy, không lẫn lộn với logic bên ngoài (AI, UI, KiCad), giúp dễ mở rộng và test.
- **Chuẩn hóa dữ liệu:** Sử dụng enum và value objects để tránh "tai họa" như typo, Any quá linh hoạt, hoặc dữ liệu không kiểm soát (từ chối dict/list/function trong tham số).
- **Hỗ trợ rules engine:** Cung cấp cấu trúc dễ xử lý cho engine xử lý quy tắc (sẽ triển khai ở giai đoạn sau), như kiểm tra business rules dựa trên loại linh kiện và ràng buộc.
- **Tính bất biến (immutability):** Ngăn chặn source of truth bị phá hủy bởi các layer khác, đảm bảo Circuit là immutable aggregate root.
- **Dễ dàng mở rộng:** Thiết kế cho phép thêm component mới mà không phá vỡ cấu trúc, nhưng giữ chặt chẽ với validation để tránh partial circuit không hợp lệ.

## Cấu trúc
File được tổ chức theo thứ tự logic từ đơn giản đến phức tạp:
1. **Imports:** Bao gồm `annotations`, `dataclass`, `field`, `Enum`, `MappingProxyType`, và `typing` để hỗ trợ kiểu dữ liệu đệ quy, immutable và validation.
2. **Enums:**
   - `ComponentType`: Liệt kê loại linh kiện cố định (resistor, capacitor, v.v.).
   - `PortDirection`: Liệt kê hướng port cố định (input, output, power, ground).
3. **Value Objects:**
   - `ParameterValue`: Giá trị tham số với value (int/float/str) và unit, validation chống None hoặc loại không hợp lệ.
   - `PinRef`: Tham chiếu chân linh kiện với component_id và pin_name, validation chống trống.
4. **Entities:**
   - `Component`: Linh kiện với id, type, pins (tuple), parameters (dict immutable). Validation: kiểm tra pins, parameters, và business rules cơ bản (ví dụ: resistor cần "resistance").
   - `Net`: Kết nối với name và connected_pins (tuple PinRef). Validation: chống trống, duplicate pin, và kiểu dữ liệu.
   - `Port`: Giao diện với name, net_name, direction (optional enum). Validation: chống trống và kiểu sai.
   - `Constraint`: Ràng buộc với name, value, unit. Validation: name không trống.
5. **Aggregate Root:**
   - `Circuit`: Tập hợp với name, _components/_nets/_ports/_constraints (internal mutable, nhưng public là proxy immutable).
     - `__post_init__`: Defensive copy và thiết lập proxy.
     - `validate_basic()`: Kiểm tra toàn bộ invariants (khóa khớp, tồn tại tham chiếu, pin không duplicate).
     - Helper methods: `get_component()`, `get_net()`.
     - Copy helper: `with_component()` để tạo bản sao với component mới (giữ immutability).
Mỗi lớp đều có `__post_init__` cho validation và `to_dict()` cho serialization.

## Vai trò
Trong kiến trúc tổng thể của dự án (electronic-chatbot), file `entities.py` đóng vai trò là nền tảng domain layer:
  - **Source of Truth:** Là nơi lưu trữ dữ liệu mạch điện thuần túy, được các layer khác (application, infrastructure) sử dụng mà không sửa đổi trực tiếp.
  - **Boundary cho DDD:** Là bounded context cho "circuits" domain, tách biệt khỏi các domain khác (AI logic, KiCad export).
  - **Input cho Rules Engine:** Cung cấp dữ liệu chuẩn hóa để engine kiểm tra quy tắc điện tử (ví dụ: kiểm tra topology dựa trên nets và components).
  - **Hỗ trợ Immutability và SOA (Single Source of Authority):** Ngăn chặn mutable state lan tỏa, đảm bảo chỉ Circuit kiểm soát dữ liệu.
  - **Facilitator cho Development:** Enum và validation giúp developer tránh lỗi, hỗ trợ auto-complete và dễ debug. Copy helpers cho phép xây dựng circuit dần dần mà giữ immutability.

Vai trò này giúp hệ thống scalable, maintainable, và giảm bug từ dữ liệu không nhất quán.

## Review Tổng Quan
**Điểm mạnh:**
- **Thiết kế vững chắc:** Sử dụng dataclass frozen và proxy để thực thi immutability, rất tốt cho domain model. Validation invariants toàn diện (cơ bản và business) bảo vệ dữ liệu hiệu quả.
- **Chuẩn hóa tốt:** Enum và value objects loại bỏ "primitive obsession" (sử dụng string/raw dict gây lỗi), hỗ trợ rules engine tương lai.
- **Tách biệt rõ ràng:** Không lẫn lộn logic bên ngoài, phù hợp DDD. Serialization dễ dàng với `to_dict()`.
- **Mở rộng tiềm năng:** Có TODO để dời business validation sang rules.py, giúp linh hoạt hơn (hỗ trợ partial circuit hoặc custom topology).
- **An toàn:** Defensive copy và kiểm tra duplicate pin/net/port ngăn chặn nhiều lỗi phổ biến trong mô hình mạch.

**Điểm cần cải thiện:**
- **Business Validation:** Hiện hard-code trong `__post_init__` của Component (ví dụ: resistor cần "resistance"). Nên dời sang rules engine riêng để tránh entity "biết quá nhiều" về kiến thức điện tử, giúp dễ mở rộng cho custom components.
- **Scalability:** Collections trong Circuit dùng dict, tốt cho lookup nhanh nhưng nếu circuit lớn (hàng nghìn components), có thể cần cấu trúc dữ liệu tối ưu hơn (ví dụ: graph cho nets).
- **Error Handling:** Errors là ValueError/TypeError, tốt nhưng có thể dùng custom exceptions (ví dụ: CircuitValidationError) để dễ catch và log.
- **Documentation:** Docstrings chi tiết, nhưng có thể thêm examples usage (ví dụ: cách tạo Circuit đầy đủ).
- **Testing:** File này lý tưởng cho unit tests (test validation, immutability), nên khuyến nghị thêm test suite.