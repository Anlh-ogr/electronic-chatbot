# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\template_builder.py
"""
Template Builder - Wrapper Tương Thích Ngược

File này đã được refactor, tách toàn bộ chức năng thành các module riêng biệt trong thư mục builder/:
  - builder/common.py: Xử lý chung (chuỗi E, metadata, tính toán linh kiện, metadata KiCad, gợi ý layout PCB...)
  - builder/bjt.py: Sinh mạch khuếch đại BJT (CE, CC, CB)
  - builder/mosfet.py: Sinh mạch khuếch đại MOSFET (CS, CD, CG)
  - builder/opamp.py: Sinh mạch khuếch đại Op-Amp
  - builder/parametric.py: Bộ máy sinh mạch tham số hóa (parametric engine)
  - builder/factory.py: API tạo amplifier đơn giản hóa (factory)

File này chỉ còn vai trò "wrapper" để giữ tương thích ngược, re-export toàn bộ API công khai từ builder/.

Khuyến nghị: Code mới nên import trực tiếp từ builder/:
    from app.domains.circuits.builder import BJTConfig, BJTAmplifierBuilder

Các import cũ vẫn hoạt động:
    from app.domains.circuits.template_builder import BJTConfig, BJTAmplifierBuilder

---

Original module documentation:

Module chịu trách nhiệm sinh tự động các mạch khuếch đại (amplifiers) với đầy đủ topologies.
Thiết kế theo Domain-Driven Design (DDD), thuộc tầng domain, chỉ chứa logic nghiệp vụ sinh mạch.

Template Builder - Amplifier Topologies: hỗ trợ đầy đủ các dạng mạch khuếch đại:
1. BJT Topologies: CE (Common Emitter), CC (Common Collector), CB (Common Base)
2. FET/MOSFET Topologies: CS (Common Source), CD (Common Drain/Source Follower), CG (Common Gate)
3. Op-Amp Configurations: Inverting, Non-Inverting, Differential, Instrumentation
4. Operation Classes: Class A, Class AB Push-Pull, Class B Push-Pull, Class C Tuned, Class D Switching
5. Special Amplifiers: Darlington Pair, Multi-Stage Cascade

Tính năng:
 * Hỗ trợ KiCad metadata (library_id, symbol_name, footprint)
 * PCB hints cho layout và routing
 * Tự động tính toán giá trị linh kiện theo series chuẩn (E6, E12, E24, E96)
 * Parametric design - user có thể override bất kỳ giá trị nào
 * Validation nghiệp vụ đầy đủ
"""

import warnings

# Re-export all public APIs from builder submodule for backward compatibility
from .builder import (
    # Common utilities
    PreferredSeries,
    AmplifierTopology,
    ComponentMetadata,
    PCBHints,
    BuildOptions,
    PowerAmpConfig,
    SpecialAmpConfig,
    ComponentCalculator,
    KiCadMetadata,
    PCBHintProvider,
    
    # BJT builders
    BJTConfig,
    BJTCalculator,
    BJTAmplifierBuilder,
    
    # MOSFET builders
    MOSFETConfig,
    MOSFETCalculator,
    MOSFETAmplifierBuilder,
    
    # Op-Amp builders
    OpAmpConfig,
    OpAmpCalculator,
    OpAmpAmplifierBuilder,
    
    # Special topology builders
    DarlingtonCalculator,
    DarlingtonAmplifierBuilder,
    MultiStageCalculator,
    MultiStageAmplifierBuilder,
    
    # Parametric engine
    ParametricEngine,
    
    # Factory
    AmplifierFactory,
)

# Backward compatibility aliases for legacy class names used in tests/docs
BJTAmplifierConfig = BJTConfig
BJTAmplifierBuildConfig = BJTConfig
OpAmpAmplifierConfig = OpAmpConfig

# Deprecation warning for legacy imports
warnings.warn(
    "Importing from template_builder.py is deprecated. "
    "Please import from 'app.domains.circuits.builder' instead. "
    "Example: from app.domains.circuits.builder import BJTConfig, BJTAmplifierBuilder",
    DeprecationWarning,
    stacklevel=2
)

__all__ = [
    # Common
    "PreferredSeries",
    "AmplifierTopology",
    "ComponentMetadata",
    "PCBHints",
    "BuildOptions",
    "PowerAmpConfig",
    "SpecialAmpConfig",
    "ComponentCalculator",
    "KiCadMetadata",
    "PCBHintProvider",
    
    # BJT
    "BJTConfig",
    "BJTCalculator",
    "BJTAmplifierBuilder",
    
    # MOSFET
    "MOSFETConfig",
    "MOSFETCalculator",
    "MOSFETAmplifierBuilder",
    
    # Op-Amp
    "OpAmpConfig",
    "OpAmpCalculator",
    "OpAmpAmplifierBuilder",
    
    # Special topology
    "DarlingtonCalculator",
    "DarlingtonAmplifierBuilder",
    "MultiStageCalculator",
    "MultiStageAmplifierBuilder",
    
    # Parametric
    "ParametricEngine",
    
    # Factory
    "AmplifierFactory",
    
    # Backward compatibility aliases
    "BJTAmplifierConfig",
    "BJTAmplifierBuildConfig",
    "OpAmpAmplifierConfig",
]
