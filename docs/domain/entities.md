# Entities trong Circuits Domain

Tài liệu này mô tả file `entities.py` trong domain circuits của dự án electronic-chatbot. File này định nghĩa các thực thể (entities) cốt lõi đại diện cho mạch điện tử, tập trung vào logic domain thuần túy, không lẫn lộn với AI, KiCad hoặc UI. Tất cả các lớp đều được thiết kế immutable (bất biến) để bảo vệ source of truth (nguồn sự thật) và đảm bảo tính nhất quán dữ liệu.

Dưới đây là phân tích cập nhật theo các khía cạnh: chức năng, mục tiêu, cấu trúc, vai trò và review tổng quan.


## Chức năng
File `entities.py` cung cấp các lớp, enum và value object để mô hình hóa các thành phần cơ bản của mạch điện tử. Các chức năng chính:

- **Định nghĩa loại linh kiện và hướng port:**
   - Sử dụng enum (`ComponentType`, `PortDirection`) để liệt kê các loại linh kiện (resistor, capacitor, bjt, ...), hướng port (input, output, power, ground), giúp chuẩn hóa và tránh lỗi nhập liệu.
- **Mô hình hóa tham số và tham chiếu chân:**
   - `ParameterValue`: Chuẩn hóa giá trị tham số (chỉ nhận int, float, str, có thể kèm đơn vị), chống None/type lỗi.
   - `PinRef`: Tham chiếu đến chân cụ thể của linh kiện, đảm bảo không trống và đúng kiểu.
- **Định nghĩa entity chính:**
   - `Component`: Linh kiện với id, type, pins (tuple), parameters (immutable dict). Validation kiểm tra số chân, tham số bắt buộc theo loại linh kiện.
   - `Net`: Kết nối giữa các chân linh kiện. Validation kiểm tra tên, số lượng chân, không duplicate, đúng kiểu PinRef. Đặc biệt, các net tên "INPUT", "OUTPUT", "POWER", "GROUND" được phép chỉ có 1 PinRef, các net khác phải ≥2.
   - `Port`: Giao diện mạch với bên ngoài, liên kết net và hướng. Validation kiểm tra tên, net_name, direction đúng kiểu.
   - `Constraint`: Ràng buộc kỹ thuật (ví dụ: gain, vcc), validation name không trống.
- **Tập hợp toàn bộ mạch:**
   - `Circuit`: Aggregate root, chứa các collection (component, net, port, constraint) dưới dạng immutable. Thực hiện validation tổng hợp qua nhiều bước:
      1. Kiểm tra khóa/id khớp.
      2. Kiểm tra tham chiếu tồn tại (PinRef, net_name).
      3. Kiểm tra mỗi pin chỉ thuộc 1 net.
      4. Thu thập lỗi vào list, chỉ raise exception nếu có lỗi (error aggregation pattern).
- **Serialization:**
   - Mỗi class đều có `to_dict()` để chuyển đổi sang dict, phục vụ lưu trữ, API, UI.
- **Bảo vệ bất biến:**
   - Sử dụng `dataclass(frozen=True)`, `MappingProxyType` cho dict, copy phòng thủ để ngăn sửa đổi từ bên ngoài.


## Mục tiêu
Mục tiêu chính của file này là xây dựng domain model vững chắc, tuân thủ DDD, tập trung vào:
- **Bảo vệ invariants:** Đảm bảo dữ liệu luôn nhất quán (pin không duplicate, tham số đúng loại, net hợp lệ, ...), tránh bug logic ở các tầng khác.
- **Tách biệt concerns:** Domain thuần túy, không dính logic ngoài (AI, UI, KiCad), dễ mở rộng/test.
- **Chuẩn hóa dữ liệu:** Enum, value object giúp loại bỏ lỗi nhập liệu, kiểm soát chặt chẽ kiểu dữ liệu.
- **Hỗ trợ rules engine:** Cấu trúc sẵn sàng cho engine kiểm tra business rules (dựa trên entity, constraint, ...).
- **Bất biến tuyệt đối:** Ngăn chặn mọi sửa đổi ngoài ý muốn, bảo vệ source of truth.
- **Dễ mở rộng:** Có thể thêm entity mới, mở rộng validation mà không phá vỡ cấu trúc cũ.


## Cấu trúc
File được tổ chức từ đơn giản đến phức tạp:
1. **Imports:** Hỗ trợ immutable, typing, defensive copy.
2. **Enums:**
   - `ComponentType`: Loại linh kiện (resistor, capacitor, bjt, ...).
   - `PortDirection`: Hướng port (input, output, power, ground).
3. **Value Objects:**
   - `ParameterValue`: Giá trị tham số (int/float/str, unit), validation chống None/type lỗi.
   - `PinRef`: Tham chiếu chân linh kiện, validation chống trống.
4. **Entities:**
   - `Component`: id, type, pins (tuple), parameters (immutable dict). Validation kiểm tra số chân, tham số bắt buộc.
   - `Net`: name, connected_pins (tuple PinRef). Validation: tên, số chân, không duplicate, đúng kiểu. Rule đặc biệt: net "INPUT", "OUTPUT", "POWER", "GROUND" cho phép 1 PinRef, net khác phải ≥2.
   - `Port`: name, net_name, direction. Validation: chống trống, đúng kiểu.
   - `Constraint`: name, value, unit. Validation: name không trống.
5. **Aggregate Root:**
   - `Circuit`:
     - Thuộc tính: name, _components, _nets, _ports, _constraints (internal mutable, public là proxy immutable).
     - `__post_init__`: Thiết lập proxy, gọi validate_basic().
     - `validate_basic()`: Gọi lần lượt các bước validation, thu thập lỗi vào list, chỉ raise nếu có lỗi (error aggregation).
     - Helper: `get_component()`, `get_net()`, `with_component()` (copy bất biến).
     - Mỗi class đều có `to_dict()` cho serialization.

## Kiến trúc sử dụng & Giải thích lựa chọn

### 1. Vì sao dùng dataclass (frozen=True)?
- Đảm bảo bất biến (immutability) cho mọi entity: Khi một entity được tạo ra, không thể thay đổi thuộc tính của nó. Điều này bảo vệ source of truth, tránh bug do thay đổi ngoài ý muốn từ các tầng khác.
- Tự động sinh constructor, repr, eq giúp code ngắn gọn, dễ debug, dễ test.
- `frozen=True` kết hợp với MappingProxyType giúp bảo vệ cả thuộc tính đơn giản lẫn dict nội bộ.

### 2. Vì sao dùng MappingProxyType cho dict?
- Dù dataclass(frozen=True) bảo vệ thuộc tính, nhưng nếu thuộc tính là dict thì bản thân dict vẫn mutable (có thể sửa nội dung qua reference).
- MappingProxyType biến dict thành read-only, mọi thao tác sửa đổi sẽ raise exception ngay lập tức.
- Đảm bảo không ai có thể sửa components, nets, ports, constraints của Circuit sau khi khởi tạo.

### 3. Type hint "-> dict", "-> None" có ý nghĩa gì?
- `-> dict`: Hàm trả về một dictionary (thường dùng cho serialization, ví dụ: `to_dict()` để chuyển entity sang dạng dict cho API, lưu trữ, UI).
- `-> None`: Hàm không trả về giá trị, chỉ thực hiện side-effect (ví dụ: validation, cập nhật errors list, ...). Đây là pattern phổ biến cho các hàm kiểm tra, xác thực.
- Type hint giúp IDE, linter, và developer hiểu rõ contract của hàm, giảm bug, tăng khả năng tự động kiểm tra type.

### 4. Vì sao chia nhỏ validation thành nhiều hàm?
- Mỗi hàm validation kiểm tra một invariant riêng biệt (khóa khớp, tham chiếu tồn tại, pin unique, ...), giúp code dễ đọc, dễ test, dễ mở rộng.
- Thu thập lỗi vào list thay vì raise ngay lập tức, giúp báo cáo toàn bộ lỗi một lần, thuận tiện cho debug và UI.

### 5. Vì sao dùng tuple thay vì list cho pins?
- Tuple là immutable, không thể thêm/xóa phần tử sau khi tạo, phù hợp với triết lý bất biến của domain.
- Đảm bảo danh sách chân linh kiện không bị thay đổi ngoài ý muốn.

### 6. Vì sao dùng Enum cho ComponentType, PortDirection?
- Enum giúp chuẩn hóa giá trị, tránh lỗi typo, hỗ trợ auto-complete, và dễ mở rộng khi thêm loại mới.
- So với string thuần, Enum an toàn hơn, dễ kiểm soát logic nghiệp vụ.

### 7. Vì sao không cho phép dict/list/function làm parameter value?
- Đảm bảo mọi tham số đều đơn giản, dễ serialize, dễ kiểm tra type, tránh bug khi truyền dữ liệu phức tạp qua API hoặc lưu trữ.

### 8. Pattern error aggregation (thu thập lỗi):
- Thay vì raise exception ngay khi gặp lỗi đầu tiên, validation sẽ thu thập tất cả lỗi vào list, cuối cùng mới raise nếu có lỗi.
- Giúp người dùng/dev biết toàn bộ vấn đề cùng lúc, thuận tiện cho UI và debug.

### 9. Vì sao Circuit là aggregate root?
- Circuit kiểm soát toàn bộ thành phần con (component, net, port, constraint), đảm bảo mọi invariant tổng thể.
- Các thao tác thêm/sửa đều phải thông qua Circuit, không thể sửa trực tiếp entity con, bảo vệ SOA (Single Source of Authority).


## Vai trò
Trong kiến trúc tổng thể của dự án, file `entities.py` là nền tảng domain layer:
- **Source of Truth:** Lưu trữ dữ liệu mạch điện thuần túy, các layer khác chỉ đọc, không sửa trực tiếp.
- **Boundary cho DDD:** Là bounded context cho "circuits" domain, tách biệt khỏi AI, UI, KiCad.
- **Input cho Rules Engine:** Chuẩn hóa dữ liệu cho engine kiểm tra quy tắc điện tử (topology, ràng buộc, ...).
- **Hỗ trợ Immutability và SOA:** Ngăn mutable state lan tỏa, chỉ Circuit kiểm soát dữ liệu.
- **Facilitator cho Development:** Enum, validation giúp dev tránh lỗi, auto-complete, debug dễ. Copy helpers hỗ trợ xây dựng circuit bất biến.

Vai trò này giúp hệ thống scalable, maintainable, giảm bug từ dữ liệu không nhất quán, và sẵn sàng mở rộng cho các business rule phức tạp.


## Review Tổng Quan
**Điểm mạnh:**
- **Thiết kế vững chắc:** Sử dụng dataclass frozen, MappingProxyType, defensive copy để thực thi immutability. Validation invariants toàn diện, chia nhỏ từng bước, bảo vệ dữ liệu hiệu quả.
- **Chuẩn hóa tốt:** Enum, value object loại bỏ primitive obsession, hỗ trợ rules engine tương lai.
- **Tách biệt rõ ràng:** Không lẫn logic ngoài, phù hợp DDD. Serialization dễ dàng với `to_dict()`.
- **Error aggregation:** Validation thu thập lỗi vào list, chỉ raise nếu có lỗi, giúp debug và log dễ hơn.
- **Rule đặc biệt rõ ràng:** Net "INPUT", "OUTPUT", "POWER", "GROUND" cho phép 1 PinRef, các net khác phải ≥2, dễ mở rộng cho topology đặc biệt.
- **Mở rộng tiềm năng:** Có thể dời business validation sang rules.py để linh hoạt hơn.

**Điểm cần cải thiện:**
- **Business Validation:** Hiện vẫn hard-code trong entity (ví dụ: resistor cần "resistance"). Nên dời sang rules engine riêng để entity không "biết quá nhiều" về domain knowledge.
- **Scalability:** Nếu circuit lớn, có thể cần cấu trúc dữ liệu tối ưu hơn dict (graph cho net).
- **Error Handling:** Nên bổ sung custom exception (CircuitValidationError) thay vì ValueError/TypeError để dễ catch/log.
- **Documentation:** Có thể thêm ví dụ usage, test case mẫu.
- **Testing:** Nên bổ sung test suite cho validation, immutability, serialization.