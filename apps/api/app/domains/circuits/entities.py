# .\thesis\electronic-chatbot\apps\api\app\domains\circuits\entities.py
""" ThÃ´ng tin chung:
Thiáº¿t káº¿ há»‡ thá»‘ng theo kiáº¿n trÃºc Domain-Driven Design (DDD), Ä‘áº·t domain (nghiá»‡p vá»¥) lÃ  cá»‘t lÃµi trung tÃ¢m, xÃ¢y dá»±ng mÃ´ hÃ¬nh kiáº¿n trÃºc pháº£n Ã¡nh chÃ­nh xÃ¡c cÃ¡c quy táº¯t vÃ  logic.
ÄÃ³ng vai trÃ² lÃ  táº§ng domain trong kiáº¿n trÃºc nhiá»u táº§ng, tÃ¡ch biá»‡t rÃµ rÃ ng vá»›i cÃ¡c táº§ng khÃ¡c nhÆ° application, infrastructure, interface, tool,...
 * Trong há»‡ thá»‘ng tá»•ng quan Domain Entities náº±m trong lá»›p Service Layer, chá»©a cÃ¡c nghiá»‡p vá»¥ xá»­ lÃ½.
 * Trong há»‡ thá»‘ng kiáº¿n trÃºc Domain Entities náº±m trong Khá»‘i xá»­ lÃ½ trung tÃ¢m, Ä‘Ã³ng vai trÃ² "bá»™ nÃ£o" cá»§a há»‡ thá»‘ng.
Circuit Domain Entities lÃ  táº­p há»£p cÃ¡c thá»±c thá»ƒ (entities) vÃ  Ä‘á»‘i tÆ°á»£ng giÃ¡ trá»‹ (value objects) Ä‘áº¡i diá»‡n cho cÃ¡c khÃ¡i niá»‡m vÃ  quy táº¯c trong lÄ©nh vá»±c máº¡ch Ä‘iá»‡n tá»­, bao gá»“m ("linh kiá»‡n", "dÃ¢y ná»‘i", "ports", "rÃ ng buá»™c", "máº¡ch").
Tuyá»‡t Ä‘á»‘i khÃ´ng Ä‘Æ°á»£c chá»©a AI Logic, KiCad Logic, UI Logic trÃ¡nh phÃ¡ vá»¡ Source of Truth.
Chá»‰ Ä‘Æ°á»£c chá»©a nghiá»‡p vá»¥ thuáº§n tÃºy cá»§a domain vá»›i cÃ¡c báº¥t biáº¿n (validation invariants) Ä‘áº£m báº£o tÃ­nh toÃ n váº¹n vÃ  nháº¥t quÃ¡n cá»§a dá»¯ liá»‡u.
"""


from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Dict, Optional, Tuple, Any

""" LÃ½ do sá»­ dá»¥ng thÆ° viá»‡n
__future__ : do khÃ´ng thá»ƒ sá»­ dá»¥ng má»™t class lÃ m kiá»ƒu dá»¯ liá»‡u cho má»™t biáº¿n trong chÃ­nh class Ä‘Ã³ (class chÆ°a khá»Ÿi táº¡o xong), nÃªn cáº§n import tá»« "annotations" Ä‘á»ƒ há»— trá»£ kiá»ƒu dá»¯ liá»‡u tham chiáº¿u chÃ©o (forward references).
dataclasses dataclass: gá»i frozen = True Ä‘á»ƒ táº¡o báº¥t biáº¿n (immutability) cho component, net, circuit. NgÄƒn cháº·n viá»‡c cÃ¡c layer khÃ¡c sá»­a Ä‘á»•i trá»±c tiáº¿p cÃ¡c entity nÃ y, báº£o vá»‡ Source of Truth.
dataclasses field: táº¡o trÆ°á»ng dá»¯ liá»‡u máº¡ch Ä‘á»‹nh lÃ  má»™t dict báº¥t biáº¿n (immutable dict) Ä‘á»ƒ ngÄƒn cháº·n viá»‡c sá»­a Ä‘á»•i trá»±c tiáº¿p tá»« bÃªn ngoÃ i.
enum: tá»± Ä‘á»™ng Ä‘á»‹nh nghÄ©a cÃ¡c háº±ng sá»‘ cho tá»«ng loáº¡i linh kiá»‡n, hÆ°á»›ng port, Ã©p do ngÆ°á»i/AI code pháº£i Ä‘Ãºng giÃ¡ trá»‹ Ä‘á»‹nh nghÄ©a sáºµn (ComponentType.Resistor, v.v).
mappingproxytype: frozen=True chá»‰ báº£o vá»‡ cÃ¡c biáº¿n Ä‘Æ¡n giáº£n, cÃ³ thá»ƒ bá»‹ can thiá»‡p do ngÆ°á»i. MappingProxy sáº½ bá»c Dict vÃ  biáº¿n nÃ³ thÃ nh read-only, má»i hÃ nh Ä‘á»™ng sá»­a Ä‘á»•i Ä‘á»u bá»‹ bÃ¡o lá»—i ngay láº­p tá»©c.
typing: cung cáº¥p thÃ´ng tin vá» kiá»ƒu dá»¯ liá»‡u cho cÃ¡c biáº¿n, hÃ m, há»— trá»£ syntax ":" cho biáº¿n vÃ  "->" cho giÃ¡ trá»‹ tráº£ vá» cá»§a hÃ m.
 * Dict[str, param value]: dÃ¹ng key lÃ  str vÃ  value lÃ  object. VD: {"resistance": ParameterValue(1000, "Ohm")}.
 * Optional[str]: biáº¿n cÃ³ thá»ƒ lÃ  str hoáº·c None. VD: {"unit": "Ohm"} hoáº·c {"unit": None}.
 * Tuple[str, ...]: dÃ¹ng tuple thay list vÃ¬ tuple cÃ³ tÃ­nh báº¥t biáº¿n (khÃ´ng thÃªm bá»›t cÃ¡c pháº§n tá»­ sau khi táº¡o) phÃ¹ há»£p vá»›i danh sÃ¡ch Pin linh kiá»‡n.
 * Any: sá»­ dá»¥ng cÃ¡c trÆ°á»ng dá»¯ liá»‡u linh hoáº¡t (giÃ¡ trá»‹ rÃ ng buá»™c), kiá»ƒu dá»¯ liá»‡u cÃ³ thá»ƒ tÃ¹y Ã½ (int, float, str).
"""

# ====== ENUMS ======
""" Äá»‹nh nghÄ©a cÃ¡c loáº¡i linh kiá»‡n
 Äiá»‡n trá»Ÿ: "resistor"
 Tá»¥ Ä‘iá»‡n: "capacitor"
    Tá»¥ Ä‘iá»‡n phÃ¢n: "capacitor_polarized"
 Cuá»™n cáº£m: "inductor"
 Transistor lÆ°á»¡ng cá»±c: "bjt"
    Transistor lÆ°á»¡ng cá»±c NPN: "bjt_npn"
    Transistor lÆ°á»¡ng cá»±c PNP: "bjt_pnp"
 Transistor hiá»‡u á»©ng trÆ°á»ng: "mosfet"
    Transistor hiá»‡u á»©ng trÆ°á»ng N-channel: "mosfet_n"
    Transistor hiá»‡u á»©ng trÆ°á»ng P-channel: "mosfet_p"
 Op-amp: "opamp"
 Nguá»“n Ä‘iá»‡n Ã¡p: "voltage_source"
 Nguá»“n dÃ²ng Ä‘iá»‡n: "current_source"
 Mass (Ground): "ground"
 Äi-ot: "diode"
 Káº¿t ná»‘i: "connector"
 Cá»•ng: "port"
"""
class ComponentType(Enum):
    RESISTOR = "resistor"
    CAPACITOR = "capacitor"
    CAPACITOR_POLARIZED = "capacitor_polarized"
    INDUCTOR = "inductor"
    BJT = "bjt"
    BJT_NPN = "bjt_npn"
    BJT_PNP = "bjt_pnp"
    MOSFET = "mosfet"
    MOSFET_N = "mosfet_n"
    MOSFET_P = "mosfet_p"
    OPAMP = "opamp"
    VOLTAGE_SOURCE = "voltage_source"
    CURRENT_SOURCE = "current_source"
    GROUND = "ground"
    DIODE = "diode"
    CONNECTOR = "connector"
    PORT = "port"
    SUBCIRCUIT = "subcircuit"

    # ====== helpers ======
    """ XÃ¢y dá»±ng báº£ng Ã¡nh xáº¡ alias (tÃªn thay tháº¿) sang ComponentType.
    - má»¥c Ä‘Ã­ch: cho phÃ©p nháº­n diá»‡n linh kiá»‡n tá»« nhiá»u tÃªn khÃ¡c nhau (tÃªn gá»‘c, tÃªn viáº¿t thÆ°á»ng, alias ngáº¯n).
    - há»— trá»£ nháº­p dá»¯ liá»‡u linh hoáº¡t, tÆ°Æ¡ng thÃ­ch vá»›i nhiá»u Ä‘á»‹nh dáº¡ng (json, api, ui ...).
    - chá»‰ khá»Ÿi táº¡o báº£ng alias khi cáº§n (1 láº§n), tiáº¿t kiá»‡m tÃ i nguyÃªn.
    Returns:
      * giÃ¡ trá»‹ gá»‘c enum ("resistor")
      * tÃªn viáº¿t thÆ°á»ng ("resistor")
      * tÃªn ngáº¯n phá»• biáº¿n ("nmos", "pmos", "npn", "pnp" ...)
    """
    # Báº£ng alias bá»• sung (key viáº¿t thÆ°á»ng)
    _ALIASES = None # sáº½ Ä‘Æ°á»£c khá»Ÿi táº¡o khi cáº§n, dÃ¹ng search nhanh.

    """XÃ¢y dá»±ng báº£ng Ã¡nh xáº¡ alias â†’ ComponentType (lazy, chá»‰ cháº¡y 1 láº§n)."""
    @classmethod
    def _build_aliases(cls) -> Dict[str, "ComponentType"]:
        aliases: Dict[str, ComponentType] = {}
        for member in cls:
            if member.name.startswith("_"):
                continue
            aliases[member.value] = member             # Ã¡nh xáº¡ giÃ¡ trá»‹ gá»‘c: "resistor" â†’ RESISTOR
            aliases[member.name.lower()] = member      # Ã¡nh xáº¡ tÃªn viáº¿t thÆ°á»ng: "RESISTOR" â†’ RESISTOR
        
        # ThÃªm ngoáº¡i lá»‡ alias ngáº¯n phá»• biáº¿n cho json 
        aliases["cap_polarized"] = cls.CAPACITOR_POLARIZED
        aliases["nmos"] = cls.MOSFET_N
        aliases["pmos"] = cls.MOSFET_P
        aliases["npn"] = cls.BJT_NPN
        aliases["pnp"] = cls.BJT_PNP
        aliases["block"] = cls.SUBCIRCUIT
        aliases["stage"] = cls.SUBCIRCUIT
        aliases["jumper"] = cls.CONNECTOR
        aliases["coupling"] = cls.CONNECTOR
        aliases["transformer"] = cls.INDUCTOR
        return aliases

    """Chuyá»ƒn Ä‘á»•i chuá»—i báº¥t ká»³ (tÃªn component, alias, hoa/thÆ°á»ng) -> ComponentType chuáº©n.
    - há»— trá»£ input: enum, str gá»‘c, str hoa/thÆ°á»ng, xÃ³a " ".
    - tá»± Ä‘á»™ng chuáº©n hÃ³a vá» dáº¡ng thÆ°á»ng, xÃ³a " ".
    - khá»Ÿi táº¡o báº£ng alias (náº¿u chÆ°a cÃ³) Ä‘á»ƒ tra cá»©u nhanh.
    - tÃ¬m mapping, tráº£ ComponentType tÆ°Æ¡ng á»©ng.
    - khÃ´ng tÃ¬m tháº¥y, bÃ¡o lá»—i kÃ¨m danh sÃ¡ch giÃ¡ trá»‹ há»£p lá»‡.
    Args: raw(str): chuá»—i tÃªn component/alias.
    Return: component type: enum tÆ°Æ¡ng á»©ng.
    Raises: value error: náº¿u khÃ´ng tÃ¬m tháº¥y mapping.
    """
    @classmethod
    def normalize(cls, raw: str) -> "ComponentType":
        if isinstance(raw, cls):
            return raw
        key = raw.strip().lower()
        
        # Khá»Ÿi táº¡o báº£ng alias náº¿u chÆ°a cÃ³
        if not hasattr(cls, '_alias_table') or cls._alias_table is None:
            cls._alias_table = cls._build_aliases()
        result = cls._alias_table.get(key)
        if result is not None:
            return result
        
        raise ValueError(
            f"ComponentType khÃ´ng há»£p lá»‡: '{raw}'. "
            f"CÃ¡c giÃ¡ trá»‹ há»£p lá»‡: {sorted(cls._alias_table.keys())}"
        )


""" Äá»‹nh nghÄ©a hÆ°á»›ng Port
 Input : "input"
 Output : "output"
 Nguá»“n : "power"
 Mass : "ground"
"""
class PortDirection(Enum):
    INPUT = "input"
    OUTPUT = "output"
    POWER = "power"
    GROUND = "ground"


# ====== VALUE OBJECTS ======
""" GiÃ¡ trá»‹ tham sá»‘
LÆ°u trá»¯ cÃ¡c giÃ¡ trá»‹ tham sá»‘ cá»§a linh kiá»‡n.
 * Value khÃ´ng Ä‘Æ°á»£c None, báº¯t buá»™c pháº£i cÃ³ giÃ¡ trá»‹ thá»±c táº¿.
 * Kiá»ƒm tra kiá»ƒu dá»¯ liá»‡u Ä‘á»ƒ trÃ¡nh lá»—i khi tÃ­nh toÃ¡n hoáº·c truyá»n vÃ o kiá»ƒu khÃ´ng há»£p lá»‡ (dict, list, function).
In/Out:
 * In: Any {int | float | str}
 * Out: dict {"value": int | float | str, "unit": str|None}
Chuyá»ƒn Ä‘á»•i cÃ¡c Object phá»©c táº¡p thÃ nh dá»¯ liá»‡u Ä‘Æ¡n giáº£n (cá»— mÃ¡y phiÃªn dá»‹ch) Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ database, hiá»ƒn thá»‹ UI.
"""
@dataclass(frozen=True)
class ParameterValue:
    value: Any
    unit: Optional[str] = None
    
    def __post_init__(self):
        if self.value is None:
            raise ValueError("Value khÃ´ng Ä‘Æ°á»£c None")
        if isinstance(self.value, ParameterValue):
            object.__setattr__(self, 'unit', self.value.unit or self.unit)
            object.__setattr__(self, 'value', self.value.value)
        if not isinstance(self.value, (int, float, str)):
            raise TypeError(f"Value chá»‰ cháº¥p nháº­n int|float|str, nháº­n {type(self.value)}")
            
    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "unit": self.unit
        }

    def _get_val(self, other):
        if isinstance(other, ParameterValue):
            return float(other.value)
        return float(other)

    def __truediv__(self, other):
        return float(self.value) / self._get_val(other)

    def __rtruediv__(self, other):
        return self._get_val(other) / float(self.value)

    def __mul__(self, other):
        return float(self.value) * self._get_val(other)

    def __rmul__(self, other):
        return self._get_val(other) * float(self.value)

    def __add__(self, other):
        return float(self.value) + self._get_val(other)

    def __radd__(self, other):
        return self._get_val(other) + float(self.value)

    def __sub__(self, other):
        return float(self.value) - self._get_val(other)

    def __rsub__(self, other):
        return self._get_val(other) - float(self.value)
        
    def __float__(self):
        return float(self.value)

    def __gt__(self, other):
        return float(self.value) > self._get_val(other)
        
    def __lt__(self, other):
        return float(self.value) < self._get_val(other)
        
    def __ge__(self, other):
        return float(self.value) >= self._get_val(other)
        
    def __le__(self, other):
        return float(self.value) <= self._get_val(other)
        
    def __eq__(self, other):
        if isinstance(other, ParameterValue):
            return self.value == other.value and self.unit == other.unit
        return self.value == other

""" Tham chiáº¿u chÃ¢n linh kiá»‡n
 * Táº¡o id vÃ  tÃªn chÃ¢n cá»¥ thá»ƒ cho tá»«ng linh kiá»‡n.
 * Khi káº¿t ná»‘i cÃ¡c chÃ¢n trong máº¡ch, cáº§n tham chiáº¿u Ä‘áº¿n Ä‘Ãºng chÃ¢n linh kiá»‡n.
 * Äáº£m báº£o id vÃ  tÃªn chÃ¢n cá»§a linh kiá»‡n khÃ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng.
 In/Out:
  * In: str (component_id), str (pin_name)
  * Out: dict {"component_id": str, "pin_name": str}
Chuyá»ƒn Ä‘á»•i cÃ¡c Object phá»©c táº¡p thÃ nh dá»¯ liá»‡u Ä‘Æ¡n giáº£n (cá»— mÃ¡y phiÃªn dá»‹ch) Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ hoáº·c hiá»ƒn thá»‹ UI.
"""
@dataclass(frozen=True)
class PinRef:
    component_id: str
    pin_name: str
    
    def __post_init__(self):
        if not self.component_id or not self.pin_name:
            raise ValueError("PinRef khÃ´ng há»£p lá»‡")
        
    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "pin_name": self.pin_name
        }



# ===== ENTITIES =====
""" Linh kiá»‡n váº­t lÃ½ trong máº¡ch Ä‘iá»‡n tá»­.
Äáº¡i diá»‡n cho má»™t linh kiá»‡n vá»›i cÃ¡c trÆ°á»ng:
 * id: Ä‘á»‹nh danh duy nháº¥t, khÃ´ng Ä‘Æ°á»£c trá»‘ng.
 * type: loáº¡i linh kiá»‡n (ComponentType).
 * pins: danh sÃ¡ch chÃ¢n, dáº¡ng tuple báº¥t biáº¿n, tá»‘i thiá»ƒu 2 chÃ¢n.
 * parameters: dict cÃ¡c tham sá»‘, má»—i giÃ¡ trá»‹ pháº£i lÃ  ParameterValue.
 
KiCad Metadata (há»— trá»£ pipeline má»›i vá»›i symbol chuáº©n KiCad):
 * library_id: Ä‘á»‹nh danh thÆ° viá»‡n KiCad (VD: "Device", "Amplifier_Operational").
 * symbol_name: tÃªn symbol trong KiCad (VD: "R", "C", "Q_NPN_BCE").
 * footprint: tham chiáº¿u footprint PCB (VD: "Resistor_SMD:R_0805_2012Metric").
 * symbol_version: phiÃªn báº£n/biáº¿n thá»ƒ cá»§a thÆ° viá»‡n symbol.
 * render_style: thuá»™c tÃ­nh render tÃ¹y chá»‰nh (vá»‹ trÃ­, gÃ³c xoay, style,...).

Äáº£m báº£o báº¥t biáº¿n (immutability) vÃ  kiá»ƒm tra cháº·t cháº½:
 * Táº¥t cáº£ trÆ°á»ng Ä‘á»u Ä‘Æ°á»£c xÃ¡c thá»±c khi khá»Ÿi táº¡o.
 * Má»i tham sá»‘ pháº£i lÃ  ParameterValue, Ä‘Ãºng kiá»ƒu dá»¯ liá»‡u.
 * Ãp dá»¥ng cÃ¡c quy táº¯c nghiá»‡p vá»¥: linh kiá»‡n pháº£i cÃ³ tham sá»‘ báº¯t buá»™c (VD: resistor cáº§n resistance).
 * KiCad metadata Ä‘Æ°á»£c validate: library_id yÃªu cáº§u symbol_name, cÃ¡c trÆ°á»ng pháº£i Ä‘Ãºng kiá»ƒu.
 * render_style Ä‘Æ°á»£c freeze thÃ nh immutable dict.

Input:
 * id: str
 * type: ComponentType
 * pins: tuple[str, ...]
 * parameters: dict[str, ParameterValue]
 * library_id: Optional[str]
 * symbol_name: Optional[str]
 * footprint: Optional[str]
 * symbol_version: Optional[str]
 * render_style: Optional[dict[str, Any]]

Output:
    dict: { 
        "id": str, 
        "type": str, 
        "pins": tuple[str, ...], 
        "parameters": dict[str, dict],
        "library_id": str (náº¿u cÃ³),
        "symbol_name": str (náº¿u cÃ³),
        "footprint": str (náº¿u cÃ³),
        "symbol_version": str (náº¿u cÃ³),
        "render_style": dict (náº¿u cÃ³)
    }

Chuyá»ƒn Ä‘á»•i object thÃ nh dict Ä‘Æ¡n giáº£n Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ hoáº·c hiá»ƒn thá»‹ UI.
"""
@dataclass(frozen=True)
class Component:
    id: str
    type: ComponentType
    pins: Tuple[str, ...]
    # NgÄƒn cháº·n viá»‡c immutable bá»‹ phÃ¡ (circuit.component.clear()/circuit.component["R1"]=some_fake_component -> phÃ¡ vá»¡ SOA)
    parameters: Dict[str, ParameterValue] = field(default_factory=dict)
    
    # CÃ¡c trÆ°á»ng dá»¯ liá»‡u Ä‘áº·c táº£ (metadata) trong KiCad phá»¥c vá»¥ viá»‡c tÃ­ch há»£p vÃ  hiá»ƒn thá»‹ linh kiá»‡n
    library_id: Optional[str] = None                                      # Ä‘á»‹nh dáº¡ng thÆ° viá»‡n Kicad (thÆ° viá»‡n trong folder ..\apps\api\resources\kicad\symbols\version)
    symbol_name: Optional[str] = None                                     # tÃªn kÃ½ hiá»‡u linh kiá»‡n
    footprint: Optional[str] = None                                       # tham chiáº¿u PCB footprint
    symbol_version: Optional[str] = None                                  # phiÃªn báº£n thÆ° viá»‡n
    render_style: Optional[Dict[str, Any]] = field(default_factory=dict)  # thuá»™c tÃ­nh render tÃ¹y chá»‰nh (vá»‹ trÃ­, gÃ³c xoay, style,...)
    
    def __post_init__(self):
        self._validate_identity()
        self._validate_pins()

        # kiá»ƒm tra param val : {"bjt_model": "2N2222"} sai -> pháº£i {"bjt_model": ParameterValue("2N2222")}
        params_copy = dict(self.parameters)
        self._validate_param_types(params_copy)

        # Set láº¡i field vá»›i báº£n copy immutable cho business validation
        object.__setattr__(self, "parameters", MappingProxyType(params_copy))
        self._validate_required_param()
        
        # XÃ¡c thá»±c vÃ  Ä‘Ã³ng bÄƒng dá»¯ liá»‡u
        self._validate_kicad_metadata()
        
        # ÄÃ³ng bÄƒng render_style Ä‘á»ƒ Ä‘áº£m báº£o tÃ­nh báº¥t biáº¿n
        if self.render_style:
            render_style_copy = dict(self.render_style)
            object.__setattr__(self, "render_style", MappingProxyType(render_style_copy))
        else:
            object.__setattr__(self, "render_style", MappingProxyType({}))
    
    # hÃ m kiá»ƒm tra id
    def _validate_identity(self):
        if not self.id:
            raise ValueError("ID linh kiá»‡n khÃ´ng Ä‘Æ°á»£c trá»‘ng")
    # hÃ m kiá»ƒm tra pins vÃ  sá»‘ lÆ°á»£ng pins
    def _validate_pins(self):
        if not isinstance(self.pins, tuple):
            raise TypeError(f"Pins cá»§a {self.id} cÃ³ dáº¡ng lÃ  tuple")
        # Connectors, ports, and grounds can have single pin
        single_pin_types = (
            ComponentType.CONNECTOR,
            ComponentType.PORT,
            ComponentType.GROUND,
            ComponentType.VOLTAGE_SOURCE,
            ComponentType.CURRENT_SOURCE,
        )
        if self.type not in single_pin_types:
            if len(self.pins) < 2:
                raise ValueError(f"Linh kiá»‡n {self.id} pháº£i cÃ³ Ã­t nháº¥t hai chÃ¢n")
        elif len(self.pins) < 1:
            raise ValueError(f"Linh kiá»‡n {self.id} pháº£i cÃ³ Ã­t nháº¥t má»™t chÃ¢n")
    # hÃ m kiá»ƒm tra kiá»ƒu tham sá»‘
    def _validate_param_types(self, parameters: dict = None):
        if parameters is None:
            parameters = self.parameters
        for key, val in parameters.items():
            if not isinstance(val, ParameterValue):
                raise TypeError(f"Parameter '{key}' cá»§a {self.id} pháº£i lÃ  ParameterValue")
    # NhÃ³m cÃ¡c component type cÃ¹ng nghiá»‡p vá»¥ (capacitor variants, BJT variants, v.v.)
    _CAPACITOR_FAMILY = {ComponentType.CAPACITOR, ComponentType.CAPACITOR_POLARIZED}
    _BJT_FAMILY = {ComponentType.BJT, ComponentType.BJT_NPN, ComponentType.BJT_PNP}
    _MOSFET_FAMILY = {ComponentType.MOSFET, ComponentType.MOSFET_N, ComponentType.MOSFET_P}

    # hÃ m kiá»ƒm tra tham sá»‘ báº¯t buá»™c theo loáº¡i linh kiá»‡n
    def _validate_required_param(self):
        if self.type == ComponentType.RESISTOR:
            if "resistance" not in self.parameters:
                raise ValueError(f"Resistor {self.id} pháº£i cÃ³ tham sá»‘ resistance")
        if self.type in self._CAPACITOR_FAMILY:
            if "capacitance" not in self.parameters:
                raise ValueError(f"Capacitor {self.id} pháº£i cÃ³ tham sá»‘ capacitance")
        if self.type == ComponentType.INDUCTOR:
            if "inductance" not in self.parameters:
                raise ValueError(f"Inductor {self.id} pháº£i cÃ³ tham sá»‘ inductance")
        if self.type in self._BJT_FAMILY:
            if "model" not in self.parameters:
                raise ValueError(f"BJT {self.id} pháº£i cÃ³ tham sá»‘ model")
        if self.type in self._MOSFET_FAMILY:
            if "model" not in self.parameters:
                raise ValueError(f"MOSFET {self.id} pháº£i cÃ³ tham sá»‘ model")
        if self.type == ComponentType.VOLTAGE_SOURCE:
            if "voltage" not in self.parameters:
                raise ValueError(f"Voltage source {self.id} pháº£i cÃ³ tham sá»‘ voltage")
    # hÃ m kiá»ƒm tra dá»¯ liá»‡u linh kiá»‡n (kicad metadata)
    def _validate_kicad_metadata(self):
        # Náº¿u symbol_name Ä‘Æ°á»£c cung cáº¥p, library_id pháº£i Ä‘Æ°á»£c cung cáº¥p
        if self.library_id and not self.symbol_name:
            raise ValueError(f"Component {self.id}: library_id Ä‘Æ°á»£c cung cáº¥p nhÆ°ng thiáº¿u symbol_name")
        
        # kiá»ƒm tra xÃ¡c thá»±c kiá»ƒu dá»¯ liá»‡u metadata (str)
        if self.library_id is not None and not isinstance(self.library_id, str):
            raise TypeError(f"Component {self.id}: library_id pháº£i lÃ  str, nháº­n {type(self.library_id)}")
        if self.symbol_name is not None and not isinstance(self.symbol_name, str):
            raise TypeError(f"Component {self.id}: symbol_name pháº£i lÃ  str, nháº­n {type(self.symbol_name)}")
        if self.footprint is not None and not isinstance(self.footprint, str):
            raise TypeError(f"Component {self.id}: footprint pháº£i lÃ  str, nháº­n {type(self.footprint)}")
        if self.symbol_version is not None and not isinstance(self.symbol_version, str):
            raise TypeError(f"Component {self.id}: symbol_version pháº£i lÃ  str, nháº­n {type(self.symbol_version)}")
        
        # kiá»ƒm tra xÃ¡c thá»±c kiá»ƒu dá»¯ liá»‡u render_style (dict)
        if self.render_style is not None and not isinstance(self.render_style, dict):
            raise TypeError(f"Component {self.id}: render_style pháº£i lÃ  dict, nháº­n {type(self.render_style)}")
    # chuyá»ƒn obj -> dict (API)
    def to_dict(self) -> dict:
        result = {
            "id": self.id,
            "type": self.type.value,
            "pins": self.pins,
            "parameters": {key: val.to_dict() for key, val in self.parameters.items()}
        }
        
        # ThÃªm metadata KiCad náº¿u cÃ³
        if self.library_id:
            result["library_id"] = self.library_id
        if self.symbol_name:
            result["symbol_name"] = self.symbol_name
        if self.footprint:
            result["footprint"] = self.footprint
        if self.symbol_version:
            result["symbol_version"] = self.symbol_version
        if self.render_style and len(self.render_style) > 0:
            result["render_style"] = dict(self.render_style)
        
        return result


""" DÃ¢y ná»‘i (Net) giá»¯a cÃ¡c chÃ¢n linh kiá»‡n trong máº¡ch Ä‘iá»‡n tá»­.
Äáº¡i diá»‡n cho má»™t net vá»›i cÃ¡c trÆ°á»ng:
 * name: tÃªn net, khÃ´ng Ä‘Æ°á»£c trá»‘ng.
 * connected_pins: tuple cÃ¡c PinRef, má»—i pháº§n tá»­ lÃ  tham chiáº¿u Ä‘áº¿n má»™t chÃ¢n linh kiá»‡n.

Äáº£m báº£o báº¥t biáº¿n (immutability) vÃ  kiá»ƒm tra cháº·t cháº½:
 * TÃªn net pháº£i há»£p lá»‡, khÃ´ng rá»—ng.
 * Danh sÃ¡ch chÃ¢n pháº£i lÃ  tuple PinRef, tá»‘i thiá»ƒu 2 chÃ¢n.
 * KhÃ´ng cÃ³ chÃ¢n nÃ o bá»‹ láº·p láº¡i (má»—i chÃ¢n chá»‰ xuáº¥t hiá»‡n má»™t láº§n trong net).

Input:
 * name: str
 * connected_pins: tuple[PinRef, ...]

Output:
    dict: { "name": str, "connected_pins": list[dict]}

Chuyá»ƒn Ä‘á»•i object thÃ nh dict Ä‘Æ¡n giáº£n Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ hoáº·c hiá»ƒn thá»‹ UI.
"""
@dataclass(frozen=True)
class Net:
    name: str
    connected_pins: Tuple[PinRef, ...]
    
    def __post_init__(self):
        self._validate_identity()
        self._validate_pin_count()
        self._validate_pin_refs()
        self._validate_no_duplicate_pins()
    
    # kiá»ƒm tra tÃªn
    def _validate_identity(self):
        if not self.name:
            raise ValueError("TÃªn net khÃ´ng Ä‘Æ°á»£c trá»‘ng")
    # kiá»ƒm tra sá»‘ lÆ°á»£ng chÃ¢n (Ã­t nháº¥t 1 - validation â‰¥2 náº±m á»Ÿ rules layer)
    def _validate_pin_count(self):
        if len(self.connected_pins) < 1:
            raise ValueError(f"Net '{self.name}' pháº£i cÃ³ Ã­t nháº¥t má»™t chÃ¢n Ä‘Æ°á»£c káº¿t ná»‘i (cáº§n Ã­t nháº¥t má»™t PinRef trong connected_pins)")
    # kiá»ƒm tra tham chiáº¿u
    def _validate_pin_refs(self):
        for ref in self.connected_pins:
            if not isinstance(ref, PinRef):
                raise TypeError(f"Pháº§n tá»­ '{ref}' trong connected_pins cá»§a Net '{self.name}' pháº£i lÃ  PinRef, nháº­n {type(ref)}")
    # kiá»ƒm tra trÃ¹ng chÃ¢n
    def _validate_no_duplicate_pins(self):
        seen = set()
        for ref in self.connected_pins:
            key = (ref.component_id, ref.pin_name)
            if key in seen:
                raise ValueError(f"Net '{self.name}' cÃ³ chÃ¢n '{ref.component_id}.{ref.pin_name}' bá»‹ láº·p láº¡i nhiá»u láº§n trong connected_pins (má»—i chÃ¢n chá»‰ Ä‘Æ°á»£c xuáº¥t hiá»‡n má»™t láº§n)")
            seen.add(key)
    # chuyá»ƒn obj -> dict
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "connected_pins": [ref.to_dict() for ref in self.connected_pins]
        }


""" Cá»•ng Ports
Äáº¡i diá»‡n cho giao diá»‡n giá»¯a máº¡ch vÃ  tháº¿ giá»›i bÃªn ngoÃ i (VD: VIN, VOUT, VCC, GND).
Äáº£m báº£o tÃªn port vÃ  tÃªn net khÃ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng, direction (hÆ°á»›ng) pháº£i lÃ  Enum PortDirection náº¿u cÃ³.
In/Out:
 * In: str (name), str (net_name), Optional[PortDirection] (direction)
 * Out: dict {"name": str, "net_name": str, "direction": str|None}
Validation:
 * name: khÃ´ng Ä‘Æ°á»£c rá»—ng
 * net_name: khÃ´ng Ä‘Æ°á»£c rá»—ng
 * direction: náº¿u cÃ³, pháº£i lÃ  PortDirection
Chuyá»ƒn Ä‘á»•i object thÃ nh dict Ä‘Æ¡n giáº£n Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ hoáº·c hiá»ƒn thá»‹ UI.
"""
@dataclass(frozen=True)
class Port:
    name: str
    net_name: str
    direction: Optional[PortDirection] = None

    def __post_init__(self):
        if not self.name:
            raise ValueError("TÃªn port khÃ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng")
        if not self.net_name:
            raise ValueError(f"Port '{self.name}' pháº£i káº¿t ná»‘i Ä‘áº¿n má»™t net (net_name khÃ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng)")
        if self.direction is not None and not isinstance(self.direction, PortDirection):
            raise TypeError(f"Port '{self.name}': direction pháº£i lÃ  PortDirection enum, nháº­n {type(self.direction)}")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "net_name": self.net_name,
            "direction": self.direction.value if self.direction else None
        }


""" RÃ ng buá»™c giá»¯a cÃ¡c tham sá»‘
Äáº¡i diá»‡n cho Ã½ Ä‘á»‹nh ká»¹ thuáº­t (khÃ´ng pháº£i rule), dÃ¹ng lÃ m input cho rules engine.
Äáº£m báº£o tÃªn constraint khÃ´ng Ä‘Æ°á»£c Ä‘á»ƒ trá»‘ng.
In/Out:
 * In: str (name), Any (value), Optional[str] (unit)
 * Out: dict {"name": str, "value": Any, "unit": str|None}
Validation:
 * name: khÃ´ng Ä‘Æ°á»£c rá»—ng
Chuyá»ƒn Ä‘á»•i object thÃ nh dict Ä‘Æ¡n giáº£n Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ hoáº·c hiá»ƒn thá»‹ UI.
"""
@dataclass(frozen=True)
class Constraint:
    name: str
    value: Any
    unit: Optional[str] = None
    constraint_type: Optional[str] = None   # structured type: "voltage_range", "current_limit", "power_rating_min", ...
    target: Optional[str] = None            # component/net target: "Q1", "VCC", ...
    min_value: Optional[float] = None       # min bound (náº¿u cÃ³)
    max_value: Optional[float] = None       # max bound (náº¿u cÃ³)

    def __post_init__(self):
        if not self.name:
            raise ValueError("RÃ ng buá»™c pháº£i cÃ³ tÃªn")
        
    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "value": self.value,
            "unit": self.unit
        }
        if self.constraint_type is not None:
            result["constraint_type"] = self.constraint_type
        if self.target is not None:
            result["target"] = self.target
        if self.min_value is not None:
            result["min_value"] = self.min_value
        if self.max_value is not None:
            result["max_value"] = self.max_value
        return result


# ===== AGGREGATE ROOT =====
"""
ToÃ n bá»™ máº¡ch Ä‘iá»‡n tá»­ (Aggregate Root)
Äáº¡i diá»‡n cho toÃ n bá»™ máº¡ch Ä‘iá»‡n tá»­, kiá»ƒm soÃ¡t vÃ  xÃ¡c thá»±c táº¥t cáº£ thÃ nh pháº§n: linh kiá»‡n, dÃ¢y ná»‘i (net), cá»•ng (port), rÃ ng buá»™c (constraint).
- Äáº£m báº£o báº¥t biáº¿n (immutability):
  * Sá»­ dá»¥ng dataclass(frozen=True) vÃ  MappingProxyType Ä‘á»ƒ ngÄƒn cháº·n sá»­a Ä‘á»•i trá»±c tiáº¿p tá»« bÃªn ngoÃ i.
  * Má»i trÆ°á»ng dá»¯ liá»‡u Ä‘á»u lÃ  immutable, báº£o vá»‡ Source of Truth (SOA).
- Kiá»ƒm soÃ¡t toÃ n váº¹n dá»¯ liá»‡u:
  * XÃ¡c thá»±c tÃªn máº¡ch khÃ´ng Ä‘Æ°á»£c rá»—ng.
  * Má»—i component/net/port/constraint pháº£i cÃ³ key khá»›p vá»›i id/name.
  * Net: má»i chÃ¢n pháº£i tham chiáº¿u Ä‘Ãºng linh kiá»‡n vÃ  pin.
  * Port: pháº£i káº¿t ná»‘i Ä‘áº¿n net há»£p lá»‡.
  * KhÃ´ng cÃ³ pin nÃ o thuá»™c nhiá»u net (duy nháº¥t).
- Chuyá»ƒn Ä‘á»•i object thÃ nh dict Ä‘Æ¡n giáº£n Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ hoáº·c hiá»ƒn thá»‹ UI.

In/Out:
 * In:
    - name: str
    - id: Optional[str]
    - _components: Dict[str, Component] (key lÃ  id linh kiá»‡n)
    - _nets: Dict[str, Net] (key lÃ  tÃªn net)
    - _ports: Dict[str, Port] (key lÃ  tÃªn port)
    - _constraints: Dict[str, Constraint] (key lÃ  tÃªn constraint)
 * Out:
    - dict: {
        "name": str,
        "components": list[dict],
        "nets": list[dict],
        "ports": list[dict],
        "constraints": list[dict]
    }

Validation:
    - name: khÃ´ng Ä‘Æ°á»£c rá»—ng
    - Má»—i component/net/port/constraint pháº£i cÃ³ key khá»›p vá»›i id/name
    - Net: má»i chÃ¢n pháº£i tham chiáº¿u Ä‘Ãºng linh kiá»‡n vÃ  pin
    - Port: pháº£i káº¿t ná»‘i Ä‘áº¿n net há»£p lá»‡
    - KhÃ´ng cÃ³ pin nÃ o thuá»™c nhiá»u net

Báº¥t biáº¿n:
    - NgÄƒn cháº·n mutable phÃ¡ vá»¡ SOA
    - ToÃ n bá»™ trÆ°á»ng lÃ  immutable (frozen=True, MappingProxyType)
    - KhÃ´ng cho phÃ©p sá»­a Ä‘á»•i trá»±c tiáº¿p tá»« bÃªn ngoÃ i

Chuyá»ƒn Ä‘á»•i:
    - to_dict(): Chuyá»ƒn object thÃ nh dict Ä‘Æ¡n giáº£n Ä‘á»ƒ truyá»n qua API, lÆ°u trá»¯ hoáº·c hiá»ƒn thá»‹ UI.
"""
@dataclass(frozen=True)
class Circuit:
    name: str
    id: Optional[str] = None
    _components: Dict[str, Component] = field(default_factory=dict)     # component_id -> Component: key lÃ  id linh kiá»‡n, value la Component
    _nets: Dict[str, Net] = field(default_factory=dict)                 # net_name -> Net : key la ten net, value la Net
    _ports: Dict[str, Port] = field(default_factory=dict)               # port_name -> Port : key la ten port, value la Port
    _constraints: Dict[str, Constraint] = field(default_factory=dict)   # constraint_name -> Constraint : key la ten constraint, value la Constraint
    
    # Template metadata â€“ lÆ°u nguá»“n gá»‘c template cho truy váº¿t & há»c máº¡ch máº«u
    topology_type: Optional[str] = None           # vd: "bjt_common_emitter_voltage_amplifier"
    category: Optional[str] = None                # vd: "bjt", "opamp", "power_amplifier"
    template_id: Optional[str] = None             # vd: "OP-01", "CE-02"
    tags: Tuple[str, ...] = ()                    # vd: ("common-emitter", "voltage-divider-bias")
    description: Optional[str] = None             # mÃ´ táº£ dáº¡ng tá»± nhiÃªn
    parametric: Optional[Dict[str, Any]] = None   # tham sá»‘ tunable: {"R1": {"resistance": "optional"}, ...}
    pcb_hints: Optional[Dict[str, Any]] = None    # PCB layout hints: keepout_zones, critical_nets, ...
    
    def __post_init__(self):
        # ÄÃ³ng bÄƒng metadata collections (parametric, pcb_hints)
        if self.parametric is not None:
            object.__setattr__(self, "parametric", MappingProxyType(dict(self.parametric)))
        if self.pcb_hints is not None:
            object.__setattr__(self, "pcb_hints", MappingProxyType(dict(self.pcb_hints)))
        # Táº¡o báº£n copy immutable Ä‘á»ƒ ngÄƒn cháº·n mutable phÃ¡ vá»¡ SOA
        self._freeze_internal_collection()
        # Bá»c Dict báº±ng MappingProxyType Ä‘á»ƒ biáº¿n thÃ nh read-only
        self._expose_read_only_views()
        # Thá»±c hiá»‡n xÃ¡c thá»±c cÆ¡ báº£n
        self.validate_basic()
    
    def _freeze_internal_collection(self):
        object.__setattr__(self, "components", MappingProxyType(self._components))
        object.__setattr__(self, "nets", MappingProxyType(self._nets))
        object.__setattr__(self, "ports", MappingProxyType(self._ports))
        object.__setattr__(self, "constraints", MappingProxyType(self._constraints))
    
    def _expose_read_only_views(self):
        object.__setattr__(self, "components", MappingProxyType(self._components))
        object.__setattr__(self, "nets", MappingProxyType(self._nets))
        object.__setattr__(self, "ports", MappingProxyType(self._ports))
        object.__setattr__(self, "constraints", MappingProxyType(self._constraints))
        
    def validate_basic(self) -> None:
        errors = []     # Thu tháº­p lá»—i
        self._validate_identity_and_keys(errors)
        self._validate_references(errors)
        self._validate_unique_connection(errors)
        self._raise_validation_errors(errors)
    
    # kiá»ƒm tra tÃªn-key
    def _validate_identity_and_keys(self, errors = list[str]) -> None:
        if not self.name:
                errors.append("TÃªn máº¡ch khÃ´ng Ä‘Æ°á»£c trá»‘ng")

        for comp_id, comp in self.components.items():
            if comp_id != comp.id:
                errors.append(f"Component key '{comp_id}' khÃ´ng khá»›p vá»›i id cá»§a Component: '{comp.id}'")

        for net_key, net_obj in self.nets.items():
            if net_key != net_obj.name:
                errors.append(f"Net key '{net_key}' khÃ´ng khá»›p vá»›i tÃªn cá»§a Net: '{net_obj.name}'")

        for port_key, port_obj in self.ports.items():
            if port_key != port_obj.name:
                errors.append(f"Port key '{port_key}' khÃ´ng khá»›p vá»›i tÃªn cá»§a Port: '{port_obj.name}'")
        
        for constraint_key, constraint in self.constraints.items():
            if constraint_key != constraint.name:
                errors.append(f"Constraint key '{constraint_key}' khÃ´ng khá»›p vá»›i tÃªn cá»§a Constraint: '{constraint.name}'")
    # kiá»ƒm tra tham chiáº¿u  
    def _validate_references(self, errors = list[str]) -> None:
        for net_key, net_obj in self.nets.items():
            for ref in net_obj.connected_pins:
                if ref.component_id not in self.components:
                    errors.append(f"Net '{net_key}' tham chiáº¿u Ä‘áº¿n linh kiá»‡n khÃ´ng tá»“n táº¡i: '{ref.component_id}'")
                else:
                    comp = self.components[ref.component_id]
                    if ref.pin_name not in comp.pins:
                        errors.append(f"Net '{net_key}' tham chiáº¿u Ä‘áº¿n pin khÃ´ng tá»“n táº¡i: '{ref.pin_name}' trÃªn linh kiá»‡n '{ref.component_id}'")
        
        for port_key, port_obj in self.ports.items():
            if port_obj.net_name not in self.nets:
                errors.append(f"Port '{port_key}' tham chiáº¿u Ä‘áº¿n net khÃ´ng tá»“n táº¡i: '{port_obj.net_name}'")
    # kiá»ƒm tra trÃ¹ng chÃ¢n
    def _validate_unique_connection(self, errors = list[str]) -> None:
        pin_to_net = {}
        
        # Kiá»ƒm tra má»—i pin chá»‰ thuá»™c vá» má»™t net duy nháº¥t
        for net_key, net_obj in self.nets.items():
            for ref in net_obj.connected_pins:
                pin_key = (ref.component_id, ref.pin_name)
                if pin_key in pin_to_net:
                    errors.append(
                        f"Pin '{ref.component_id}.{ref.pin_name}' bá»‹ tham chiáº¿u bá»Ÿi nhiá»u net: "
                        f"'{pin_to_net[pin_key]}' vÃ  '{net_key}'"
                    )
                pin_to_net[pin_key] = net_key
    # bÃ¡o lá»—i 
    def _raise_validation_errors(self, errors: list[str]) -> None:
        if errors:
            error_message = "XÃ¡c thá»±c máº¡ch tháº¥t báº¡i:\n" + "\n".join([f"  - {e}" for e in errors])
            raise ValueError(error_message)
    # láº¥y component/net theo id/name
    def get_component(self, component_id: str) -> Optional[Component]:
        return self.components.get(component_id)
    # láº¥y net theo tÃªn
    def get_net(self, net_name: str) -> Optional[Net]:
        return self.nets.get(net_name)
    # thÃªm/sá»­a component, tráº£ vá» Circuit má»›i
    def with_component(self, component: Component) -> "Circuit":
        new_components = dict(self.components)      # Táº¡o báº£n copy mutable
        new_components[component.id] = component    # ThÃªm/sá»­a component
        
        return Circuit(
            name=self.name,
            id=self.id,
            _components=new_components,
            _nets=dict(self.nets),                  # LuÃ´n táº¡o báº£n copy má»›i tá»« MappingProxyType Ä‘á»ƒ Ä‘áº£m báº£o báº¥t biáº¿n, khÃ´ng reuse reference _nets
            _ports=dict(self.ports),                # TÆ°Æ¡ng tá»±, copy tá»« proxy Ä‘á»ƒ trÃ¡nh mutable phÃ¡ vá»¡ SOA
            _constraints=dict(self.constraints),    # Copy tá»« proxy, khÃ´ng dÃ¹ng reference trá»±c tiáº¿p
            topology_type=self.topology_type,
            category=self.category,
            template_id=self.template_id,
            tags=self.tags,
            description=self.description,
            parametric=dict(self.parametric) if self.parametric else None,
            pcb_hints=dict(self.pcb_hints) if self.pcb_hints else None,
        )
    # chuyá»ƒn obj -> dict
    def to_dict(self) -> dict:
        result = {
            "name": self.name,
            "components": [comp.to_dict() for comp in self.components.values()],
            "nets": [net.to_dict() for net in self.nets.values()],
            "ports": [port.to_dict() for port in self._ports.values()],
            "constraints": [constraint.to_dict() for constraint in self._constraints.values()],
        }
        if self.id is not None:
            result["id"] = self.id
        if self.topology_type is not None:
            result["topology_type"] = self.topology_type
        if self.category is not None:
            result["category"] = self.category
        if self.template_id is not None:
            result["template_id"] = self.template_id
        if self.tags:
            result["tags"] = list(self.tags)
        if self.description is not None:
            result["description"] = self.description
        if self.parametric is not None:
            result["parametric"] = dict(self.parametric)
        if self.pcb_hints is not None:
            result["pcb_hints"] = dict(self.pcb_hints)
        return result
