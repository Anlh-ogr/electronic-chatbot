"""KiCad Symbol Library Mapping for Active Devices and Common Components.

This module provides a mapping from component model names and types to KiCad symbol library
references, enabling the CircuitIR compiler to correctly reference schematic symbols.

Format:
  - Component model names (e.g., TIP41C, LM741) → KiCad symbol library refs (e.g., Transistor_BJT:TIP41C)
  - Component types (e.g., bjt_npn, opamp) → generic symbol templates
  - Fallback logic for unknown components

KiCad Symbol Library Structure:
  - Library: Device, Transistor_BJT, Transistor_MOSFET, Amplifier_Operational, etc.
  - Symbol: Specific component (R, C, BJT model, Op-Amp model, etc.)
  - Format: "Library:Symbol"
"""

from typing import Dict, Optional, List, Tuple

# ────────────────────────────────────────────────────────────────────────
# 1. TRANSISTOR BJT (Bipolar Junction Transistor) - NPN & PMP
# ────────────────────────────────────────────────────────────────────────

BJT_NPN_SYMBOLS = {
    # Power Transistors (TO-220, Darlington, etc.)
    "TIP31": "Transistor_BJT:TIP31",
    "TIP31A": "Transistor_BJT:TIP31",
    "TIP31C": "Transistor_BJT:TIP31C",
    "TIP32": "Transistor_BJT:TIP32",
    "TIP32A": "Transistor_BJT:TIP32",
    "TIP32C": "Transistor_BJT:TIP32C",
    "TIP41": "Transistor_BJT:TIP41",
    "TIP41A": "Transistor_BJT:TIP41",
    "TIP41C": "Transistor_BJT:TIP41C",
    "TIP42": "Transistor_BJT:TIP42",
    "TIP42A": "Transistor_BJT:TIP42",
    "TIP42C": "Transistor_BJT:TIP42C",
    "2N3055": "Transistor_BJT:2N3055",
    "2N2222": "Transistor_BJT:2N2222",
    "2N2907": "Transistor_BJT:2N2907",
    "2SC1815": "Transistor_BJT:2SC1815",
    "2SC1943": "Transistor_BJT:2SC1943",
    "2SA1012": "Transistor_BJT:2SA1012",
    "2SA1013": "Transistor_BJT:2SA1013",
    "2SA1302": "Transistor_BJT:2SA1302",
    # Small Signal BJT (TO-92, SOT-23, etc.)
    "BC547": "Transistor_BJT:BC547",
    "BC548": "Transistor_BJT:BC548",
    "BC549": "Transistor_BJT:BC549",
    "BC557": "Transistor_BJT:BC557",
    "BC558": "Transistor_BJT:BC558",
    "BC559": "Transistor_BJT:BC559",
    "BC637": "Transistor_BJT:BC637",
    "BC807": "Transistor_BJT:BC807",
    "BC817": "Transistor_BJT:BC817",
    "BF494": "Transistor_BJT:BF494",
    "BF495": "Transistor_BJT:BF495",
    "BF496": "Transistor_BJT:BF496",
}

BJT_PNP_SYMBOLS = {
    # Power Transistors (TO-220, Darlington, etc.)
    "TIP32": "Transistor_BJT:TIP32",
    "TIP32A": "Transistor_BJT:TIP32",
    "TIP32C": "Transistor_BJT:TIP32C",
    "TIP42": "Transistor_BJT:TIP42",
    "TIP42A": "Transistor_BJT:TIP42",
    "TIP42C": "Transistor_BJT:TIP42C",
    "2N3906": "Transistor_BJT:2N3906",
    "2N2907": "Transistor_BJT:2N2907",
    # Small Signal BJT (TO-92, SOT-23, etc.)
    "BC557": "Transistor_BJT:BC557",
    "BC558": "Transistor_BJT:BC558",
    "BC559": "Transistor_BJT:BC559",
    "BC627": "Transistor_BJT:BC627",
    "BC807": "Transistor_BJT:BC807",
    "BC857": "Transistor_BJT:BC857",
    "BF464": "Transistor_BJT:BF464",
    "BF465": "Transistor_BJT:BF465",
    "BF466": "Transistor_BJT:BF466",
}

# ────────────────────────────────────────────────────────────────────────
# 2. MOSFET (Metal-Oxide-Semiconductor Field-Effect Transistor)
# ────────────────────────────────────────────────────────────────────────

MOSFET_NMOS_SYMBOLS = {
    # Power MOSFETs
    "IRF540": "Transistor_MOSFET:IRF540",
    "IRF540N": "Transistor_MOSFET:IRF540N",
    "IRF640": "Transistor_MOSFET:IRF640",
    "IRF644": "Transistor_MOSFET:IRF644",
    "IRF740": "Transistor_MOSFET:IRF740",
    "IRF840": "Transistor_MOSFET:IRF840",
    "IRL540": "Transistor_MOSFET:IRL540",
    "IRL640": "Transistor_MOSFET:IRL640",
    "IRFZ44": "Transistor_MOSFET:IRFZ44",
    "IRFZ44N": "Transistor_MOSFET:IRFZ44N",
    "BUZ11": "Transistor_MOSFET:BUZ11",
    "BUZ21": "Transistor_MOSFET:BUZ21",
    "BUZ341": "Transistor_MOSFET:BUZ341",
    # Logic-level MOSFETs
    "AO3400": "Transistor_MOSFET:AO3400",
    "2N7000": "Transistor_MOSFET:2N7000",
    "BSS138": "Transistor_MOSFET:BSS138",
    "DMN26D0": "Transistor_MOSFET:DMN26D0",
}

MOSFET_PMOS_SYMBOLS = {
    # Power MOSFETs
    "IRF9540": "Transistor_MOSFET:IRF9540",
    "IRF9540N": "Transistor_MOSFET:IRF9540N",
    "IRF9640": "Transistor_MOSFET:IRF9640",
    "IRF9740": "Transistor_MOSFET:IRF9740",
    "IRF9840": "Transistor_MOSFET:IRF9840",
    "IRFL9540": "Transistor_MOSFET:IRFL9540",
    "BUZ12": "Transistor_MOSFET:BUZ12",
    "BUZ22": "Transistor_MOSFET:BUZ22",
    "BUZ350": "Transistor_MOSFET:BUZ350",
    # Logic-level MOSFETs
    "AO3401": "Transistor_MOSFET:AO3401",
    "AO3402": "Transistor_MOSFET:AO3402",
    "2N7002": "Transistor_MOSFET:2N7002",
    "BSS84": "Transistor_MOSFET:BSS84",
}

# ────────────────────────────────────────────────────────────────────────
# 3. OPERATIONAL AMPLIFIERS (Op-Amps)
# ────────────────────────────────────────────────────────────────────────

OPAMP_SYMBOLS = {
    # Classic single op-amps
    "LM741": "Amplifier_Operational:LM741",
    "LM358": "Amplifier_Operational:LM358",
    "LM386": "Amplifier_Operational:LM386",
    "LM393": "Amplifier_Operational:LM393",
    "LM7905": "Amplifier_Operational:LM7905",
    "LM7912": "Amplifier_Operational:LM7912",
    "OPA2134": "Amplifier_Operational:OPA2134",
    "OPA27": "Amplifier_Operational:OPA27",
    "OPA2822": "Amplifier_Operational:OPA2822",
    # Fast op-amps (high bandwidth)
    "TL072": "Amplifier_Operational:TL072",
    "TL082": "Amplifier_Operational:TL082",
    "TL202": "Amplifier_Operational:TL202",
    "NE5532": "Amplifier_Operational:NE5532",
    "LT1057": "Amplifier_Operational:LT1057",
    "OPA2111": "Amplifier_Operational:OPA2111",
    # Low-offset, precision
    "OP07": "Amplifier_Operational:OP07",
    "OP97": "Amplifier_Operational:OP97",
    "LM4562": "Amplifier_Operational:LM4562",
    # Dual op-amps
    "LM358N": "Amplifier_Operational:LM358",
    "TL072": "Amplifier_Operational:TL072",
    "TL082": "Amplifier_Operational:TL082",
    "NE5532": "Amplifier_Operational:NE5532",
    "OPA2111": "Amplifier_Operational:OPA2111",
    "OPA2134": "Amplifier_Operational:OPA2134",
    "OPA2604": "Amplifier_Operational:OPA2604",
    # Quad op-amps
    "LM324": "Amplifier_Operational:LM324",
    "TL074": "Amplifier_Operational:TL074",
    "TL084": "Amplifier_Operational:TL084",
    "NE5534": "Amplifier_Operational:NE5534",
}

# ────────────────────────────────────────────────────────────────────────
# 4. DIODES
# ────────────────────────────────────────────────────────────────────────

DIODE_SYMBOLS = {
    # General purpose diodes
    "1N4148": "Device:D_Small",
    "1N4007": "Device:D",
    "1N914": "Device:D_Small",
    "1N270": "Device:D_Small",
    "1N34A": "Device:D_Small",
    "BAT85": "Device:D_Small",
    "BAS16": "Device:D_Small",
    "BAS21": "Device:D_Small",
    "BAS70": "Device:D_Small",
    "BAT54": "Device:D_Small",
    "BAT54S": "Device:D_Small",
    "BAT54C": "Device:D_Small",
    # Schottky diodes
    "1N5817": "Device:D_Schottky",
    "1N5818": "Device:D_Schottky",
    "1N5819": "Device:D_Schottky",
    "SR360": "Device:D_Schottky",
    "SB540": "Device:D_Schottky",
    "SB560": "Device:D_Schottky",
    "STPS3H100": "Device:D_Schottky",
    # Zener diodes
    "BZX55": "Device:D_Zener",
    "BZX85": "Device:D_Zener",
    "1N4728": "Device:D_Zener",
    "1N4729": "Device:D_Zener",
    "1N4730": "Device:D_Zener",
}

# ────────────────────────────────────────────────────────────────────────
# 5. PASSIVE COMPONENTS (Resistors, Capacitors, Inductors)
# ────────────────────────────────────────────────────────────────────────

PASSIVE_SYMBOLS = {
    # Resistors
    "resistor": "Device:R",
    "r": "Device:R",
    "res": "Device:R",
    # Capacitors
    "capacitor": "Device:C",
    "c": "Device:C",
    "cap": "Device:C",
    # Inductors
    "inductor": "Device:L",
    "l": "Device:L",
    "ind": "Device:L",
    # Potentiometers
    "potentiometer": "Device:R_Potentiometer",
    "pot": "Device:R_Potentiometer",
}

# ────────────────────────────────────────────────────────────────────────
# 6. INTEGRATED CIRCUITS (Other)
# ────────────────────────────────────────────────────────────────────────

IC_SYMBOLS = {
    # Voltage regulators
    "LM7805": "Regulator_Linear:LM7805",
    "LM7812": "Regulator_Linear:LM7812",
    "LM7815": "Regulator_Linear:LM7815",
    "LM7905": "Regulator_Linear:LM7905",
    "LM7912": "Regulator_Linear:LM7912",
    "LM7915": "Regulator_Linear:LM7915",
    # Logic ICs
    "74LS00": "Logic_74xxyy:74LS00",
    "555": "Timer:NE555",
    # Other ICs
    "NE556": "Timer:NE556",
}

# ────────────────────────────────────────────────────────────────────────
# MASTER MAPPING AND UTILITY FUNCTIONS
# ────────────────────────────────────────────────────────────────────────

class KiCadSymbolMapper:
    """Maps component model names and types to KiCad symbol library references."""

    def __init__(self):
        """Initialize the mapper with all symbol libraries."""
        self.bjt_npn = BJT_NPN_SYMBOLS
        self.bjt_pnp = BJT_PNP_SYMBOLS
        self.mosfet_nmos = MOSFET_NMOS_SYMBOLS
        self.mosfet_pmos = MOSFET_PMOS_SYMBOLS
        self.opamp = OPAMP_SYMBOLS
        self.diode = DIODE_SYMBOLS
        self.passive = PASSIVE_SYMBOLS
        self.ic = IC_SYMBOLS

        # Combined lookup table for fast access
        self.all_symbols: Dict[str, str] = {}
        self._build_combined_map()

    def _build_combined_map(self):
        """Build a combined symbol map from all categories."""
        for lib in [
            self.bjt_npn,
            self.bjt_pnp,
            self.mosfet_nmos,
            self.mosfet_pmos,
            self.opamp,
            self.diode,
            self.passive,
            self.ic,
        ]:
            for key, value in lib.items():
                self.all_symbols[key.upper()] = value

    def lookup_by_model(self, model_name: str) -> Optional[str]:
        """Look up KiCad symbol by component model name (case-insensitive).

        Args:
            model_name: Component model (e.g., "TIP41C", "LM741", "BC547")

        Returns:
            KiCad symbol reference or None if not found
        """
        if not model_name:
            return None
        return self.all_symbols.get(model_name.upper())

    def lookup_by_type(self, component_type: str) -> Optional[str]:
        """Look up KiCad symbol by component type (case-insensitive).

        Args:
            component_type: Component type (e.g., "bjt_npn", "opamp", "resistor")

        Returns:
            Generic KiCad symbol reference or None if not found
        """
        if not component_type:
            return None

        type_lower = component_type.lower().strip()

        type_mapping = {
            "bjt_npn": "Transistor_BJT:2N2222",  # Generic NPN fallback
            "bjt_pnp": "Transistor_BJT:2N2907",  # Generic PNP fallback
            "bjt": "Transistor_BJT:2N2222",
            "nmos": "Transistor_MOSFET:2N7000",  # Generic NMOS fallback
            "pmos": "Transistor_MOSFET:2N7002",  # Generic PMOS fallback
            "mosfet": "Transistor_MOSFET:2N7000",
            "opamp": "Amplifier_Operational:LM358",  # Generic op-amp fallback
            "diode": "Device:D",
            "zener": "Device:D_Zener",
            "schottky": "Device:D_Schottky",
            "resistor": "Device:R",
            "capacitor": "Device:C",
            "inductor": "Device:L",
            "potentiometer": "Device:R_Potentiometer",
            "regulator": "Regulator_Linear:LM7805",  # Generic regulator fallback
        }

        return type_mapping.get(type_lower)

    def get_kicad_symbol(
        self,
        component_name: str,
        component_type: str = "unknown",
        value: Optional[str] = None,
    ) -> Tuple[str, bool]:
        """Get the best-fit KiCad symbol reference.

        Strategy:
        1. Try exact lookup by component name/model
        2. Fall back to type-based lookup
        3. Return generic Device:R or Device:C if all else fails

        Args:
            component_name: Component model (e.g., "TIP41C", "BC547", "LM741")
            component_type: Component type (e.g., "bjt_npn", "opamp")
            value: Component value (optional, for passive components)

        Returns:
            Tuple of (kicad_symbol, is_exact_match)
            - kicad_symbol: KiCad symbol library reference
            - is_exact_match: True if exact lookup succeeded, False if fallback used
        """
        # Try exact lookup by model name
        if component_name:
            exact_symbol = self.lookup_by_model(component_name)
            if exact_symbol:
                return (exact_symbol, True)

        # Try type-based lookup
        if component_type:
            type_symbol = self.lookup_by_type(component_type)
            if type_symbol:
                return (type_symbol, False)

        # Fallback to generic symbols based on inferred type
        type_lower = (component_type or "").lower()
        if "resistor" in type_lower or "r_" in type_lower:
            return ("Device:R", False)
        elif "capacitor" in type_lower or "c_" in type_lower:
            return ("Device:C", False)
        elif "inductor" in type_lower or "l_" in type_lower:
            return ("Device:L", False)
        elif "diode" in type_lower:
            return ("Device:D", False)

        # Last resort: try inferring from component name patterns
        name_upper = (component_name or "").upper()
        if "TIP" in name_upper or "2N30" in name_upper:
            return ("Transistor_BJT:2N2222", False)
        elif "LM" in name_upper or "TL" in name_upper or "OP" in name_upper:
            return ("Amplifier_Operational:LM358", False)
        elif "IN4" in name_upper or "1N" in name_upper:
            return ("Device:D", False)

        # Universal fallback
        return ("Device:R", False)


# Singleton instance
_mapper = None


def get_kicad_symbol_mapper() -> KiCadSymbolMapper:
    """Get the singleton KiCad symbol mapper instance."""
    global _mapper
    if _mapper is None:
        _mapper = KiCadSymbolMapper()
    return _mapper


def resolve_kicad_symbol(
    component_name: str,
    component_type: str = "unknown",
    value: Optional[str] = None,
) -> str:
    """Convenience function to resolve KiCad symbol for a component."""
    mapper = get_kicad_symbol_mapper()
    symbol, _ = mapper.get_kicad_symbol(component_name, component_type, value)
    return symbol
