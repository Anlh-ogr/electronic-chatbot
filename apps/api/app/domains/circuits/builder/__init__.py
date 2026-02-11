"""
Builder Module - Circuit Template Builders

This module provides circuit builders for various amplifier topologies:
- BJT amplifiers (Common Emitter, Common Collector, Common Base)
- MOSFET amplifiers (Common Source, Common Drain, Common Gate)
- Op-Amp amplifiers (Inverting, Non-inverting, Differential, Instrumentation)
- Generic Parametric Engine for JSON-based templates
- AmplifierFactory for simplified circuit creation API

Usage:
    from app.domains.circuits.builder import BJTConfig, BJTAmplifierBuilder
    
    config = BJTConfig(topology="CE", gain_target=10.0, vcc=12.0)
    circuit = BJTAmplifierBuilder(config).build()

    # Or use the factory for quick creation:
    from app.domains.circuits.builder import AmplifierFactory
    circuit = AmplifierFactory.create_bjt(topology="CE", gain=10.0)

Extracted from monolithic template_builder.py for better maintainability.
"""

# Common utilities
from .common import (
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
    PowerAmpAmplifierBuilder,
)

# Special topology builders
from .specialtopo import (
    DarlingtonCalculator,
    DarlingtonAmplifierBuilder,
    MultiStageCalculator,
    MultiStageAmplifierBuilder,
)

#

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
    
    # Power Amp
    "PowerAmpConfig",
    "PowerAmpCalculator",
    "PowerAmpAmplifierBuilder",
    
    # Special topology
    "DarlingtonCalculator",
    "DarlingtonAmplifierBuilder",
    "MultiStageCalculator",
    "MultiStageAmplifierBuilder",
    
    # Parametric
    "ParametricEngine",
    
    # Factory
    "AmplifierFactory",
]
