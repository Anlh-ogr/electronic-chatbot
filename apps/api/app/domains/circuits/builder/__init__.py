""" Module Build - Build Templates for Amplifier Circuits
Module này cung cấp các builder để tạo ra các mạch khuếch đại dựa trên các thông số đầu vào. 
Các builder này hỗ trợ nhiều loại topology khác nhau, bao gồm:
- BJT amplifiers (Common Emitter, Common Collector, Common Base)
- MOSFET amplifiers (Common Source, Common Drain, Common Gate)
- Op-Amp amplifiers (Inverting, Non-inverting, Differential, Instrumentation)
- Power Amplifiers (Class A, Class B, Class AB, Class D)
- Các cấu hình đặc biệt như Darlington Pair và Multi-Stage Cascade.
"""

# Common utilities and base classes
from .common import (
    PreferredSeries,
    AmplifierTopology,
    ComponentMetadata,
    PCBHints,
    BuildOptions,
    ComponentCalculator,
    KiCadMetadata,
    PCBHintProvider,
)

# BJT builders
from .bjt import (
    BJTConfig,
    BJTCalculator,
    BJTAmplifierBuilder,
)

# MOSFET builders
from .mosfet import (
    MOSFETConfig,
    MOSFETCalculator,
    MOSFETAmplifierBuilder,
)

# Op-Amp builders
from .opamp import (
    OpAmpConfig,
    OpAmpCalculator,
    OpAmpAmplifierBuilder,
)

# Power Amp builders
from .poweramp import (
    PowerAmpConfig,
    PowerAmpCalculator,
    PowerAmpBuilder,
)

# Special topology builders
from .specialtopo import (
    SpecialAmpConfig,
    DarlingtonCalculator,
    DarlingtonAmplifierBuilder,
    MultiStageCalculator,
    MultiStageAmplifierBuilder,
)

# Parametric engine
from .parametric import (
    ParametricEngine,
)

# Factory
from .factory import (
    AmplifierFactory,
)


__all__ = [
    # Common
    "PreferredSeries",
    "AmplifierTopology",
    "ComponentMetadata",
    "PCBHints",
    "BuildOptions",
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
    
    # Power Amp
    "PowerAmpConfig",
    "PowerAmpCalculator",
    "PowerAmpBuilder",
    
    # Special topology
    "SpecialAmpConfig",
    "DarlingtonCalculator",
    "DarlingtonAmplifierBuilder",
    "MultiStageCalculator",
    "MultiStageAmplifierBuilder",
    
    # Parametric
    "ParametricEngine",
    
    # Factory
    "AmplifierFactory",
]
