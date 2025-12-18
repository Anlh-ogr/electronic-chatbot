# Circuit Scope - Phase 1 Documentation
This document outlines the various circuits that will be explored and implemented in Phase 1 of the Electronic AI Web project. Each circuit is categorized based on its primary function and application.

<!-- Mục tiêu & Phạm vi dự án -->
## 1. Project Scope
- Thiết kế mạch điện tử ở mức độ cơ bản.
- Phục vụ học tập và thực hành.
- Không thay thế kỹ sư điện tử.

<!-- Đối tượng sử dụng -->
## 2. Target Users
- Sinh viên năm 1-2 các ngành: 
    - Kỹ thuật Điện
    - Kỹ thuật Điện Tử 
    - Thiết kế Vi Mạch
    - Kỹ thuật Hệ Thống Nhúng
    - Kỹ thuật Máy Tính
    - Kỹ thuật Điện Tử Công Suất
    - Kỹ thuật Điện Tử Viễn Thông
    - Kỹ thuật Điều Khiển và Tự Động Hóa
    - Internet Vạn Vật (IoT)
    - Robot và Trí tuệ Nhân Tạo (AI/Robotic)
- Người tự học điện tử cơ bản
- Không yêu cầu kiến thức thiết kế PCB

<!-- Rule-Engine --> 
<!-- Phân loại mạch (Circuit Taxonomy) -->
## 3. Circuit Categories
### 3.1 Power Circuit
- Buck converter
- Boost converter

### 3.2 Analog Circuit
- Op-Amp Inverting Amplifier

### 3.3 Oscillator
- NE555 Music Circuit

<!-- Định nghĩa từng mạch (Circuit Definitions) -->
## 4. Circuit Definitions
### Boost Converter
- ID: boost_mt3608
- IC: MT3608
- Category: Power
- Keywords:
    - tăng áp
    - mạch tăng áp
    - module tăng áp
    - mt3608 tăng áp

    - nâng áp
    - mạch nâng áp
    - module nâng áp
    - mt3608 nâng áp
    
    - boost
    - mạch boost
    - module boost
    - mt3608 boost

    - boost converter
    - step-up converter
    - dc-dc boost converter
    - module boost converter
    - mt3608 boost converter
    - boost converter dc-dc

    - mt3608
    - mt3608 module
    - mt3608 dc-dc
    - mt3608 step-up
- Input:
    - Vin: 2-24VDC
- Output:
    - Vout: 5-28VDC
    - Iout: max 2A
    - DC ổn định, hiệu suất (~93%)

### Buck Converter
- ID: buck_lm2596
- IC: LM2596
- Category: Power
- Keywords:
    - giảm áp
    - mạch giảm áp
    - module giảm áp
    - lm2596 giảm áp

    - hạ áp
    - mạch hạ áp
    - module hạ áp
    - lm2596 hạ áp

    - buck
    - mạch buck
    - module buck
    - lm2596 buck

    - buck converter
    - step-down converter
    - dc-dc buck converter
    - module buck converter
    - lm2596 buck converter
    - buck converter dc-dc

    - lm2596
    - lm2596 module
    - lm2596 dc-dc
    - lm2596 step-down
- Input:
    - Vin: 4.5-35VDC
- Output:
    - Vout: 1.5-30VDC
    - Iout: max 3A
    - DC ổn định, hiệu suất (~92%)

### Op-Amp Inverting Amplifier
- ID: opamp_inverting_lm358
- IC: LM358
- Category: Analog
- Keywords:
    - khuếch đại đảo
    - khuếch đại âm bản
    - khuếch đại đảo lm358
  
    - mạch khuếch đại đảo
    - mạch khuếch đại opamp đảo
    - mạch khuếch đại đảo lm358

    - op-amp inverting
    - op-amp amplifier inverting
    - op-amp khuếch đại đảo pha

    - inverting amplifier
    - inverting op-amp circuit

    - lm358 inverting amplifier
    - lm358 op-amp inverting
    - lm358 amplifier
- Input:
    - Supply: Single 3-32VDC or Dual ±1.5-16VDC
    - Vin_signal: Tín hiệu analog nhỏ (typical mV đến vài V, trong common-mode range)
- Output:
    - Tín hiệu khuếch đại đảo pha (Gain = -Rf/Rin, typical gain 1–100)
    - DC-coupled, low power

### NE555 Music Circuit
- ID: oscillator_ne555_music
- IC: NE555
- Category: Oscillator
- Keywords:
    - mạch âm thanh
    - mạch nhạc
    - mạch tạo âm thanh
    - mạch tạo nhạc
    
    - ne555 âm thanh
    - ne555 nhạc
    - ne555 music circuit
    - ne555 sound circuit
    - ne555 oscillator
    - ne555 tone generator

    - music circuit
    - sound circuit
    - tone generator
- Input:
    - Vin: 5-15VDC
- Output:
    - Tín hiệu square wave (tần số điều chỉnh bằng R-C)
    - Âm thanh đơn giản qua loa/buzzer

<!-- Luật loại trừ (Out-of-Scope Rules) -->
## 5. Out-of-Scope Rules
- Mạch cao tần RF
- Mạch công suất lớn (>50W)
- Mạch liên quan trực tiếp đến điện lưới AC 220V/110V
- Thiết kế PCB đa lớp
- Mạch yêu cầu kiến thức nâng cao (SMT, EMC, v.v.)

<!-- Luật xử lý đầu vào (Rule-Engine Rules) -->
## 6. Rule-Engine Mapping
- Priority order (nếu input khớp nhiều category): Power > Analog > Oscillator
- Keyword match: case-insensitive, partial match
- Fallback: Nếu không khớp → Hỏi lại người dùng để làm rõ
Sửa phần Buck Converter: