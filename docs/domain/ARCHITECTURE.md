# 🏗️ Domain Architecture - Visual Guide

**Updated**: 2026-01-11 23:30  
**Status**: Phase 1 @ 88% | Test Coverage: 75% (64/84 passing)

## 📐 System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  API Routes │  │  Services   │  │   AI Agent  │              │
│  │  /circuits  │  │  Chatbot    │  │   Planner   │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                     │
└─────────┼────────────────┼────────────────┼─────────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DOMAIN LAYER (This)                        │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    CORE ENTITIES                         │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │Component │  │   Net    │  │   Port   │  │Constraint│  │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │   │
│  │       └─────────────┴─────────────┴─────────────┘        │   │
│  │                          │                               │   │
│  │                    ┌─────▼─────┐                         │   │
│  │                    │  Circuit  │ (Aggregate Root)        │   │
│  │                    └───────────┘                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────────────────┼──────────────────────────────┐   │
│  │          BUSINESS RULES   │                              │   │
│  │  ┌────────────────────────▼─────────────────────────┐    │   │
│  │  │         CircuitRulesEngine                       │    │   │
│  │  │                                                  │    │   │
│  │  │  ┌──────────────┐  ┌──────────────┐              │    │   │
│  │  │  │ComponentRule │  │ PinRule      │   ...x10     │    │   │
│  │  │  └──────────────┘  └──────────────┘              │    │   │
│  │  │                                                  │    │   │
│  │  │  Output: List[RuleViolation]                     │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────────────────┼──────────────────────────────┐   │
│  │     INTERMEDIATE          │                              │   │
│  │     REPRESENTATION (IR)   │                              │   │
│  │  ┌────────────────────────▼─────────────────────────┐    │   │
│  │  │         CircuitIRSerializer                      │    │   │
│  │  │                                                  │    │   │
│  │  │  Circuit ←──→ CircuitIR ←──→ JSON Dict           │    │   │
│  │  │              (with metadata)                     │    │   │
│  │  │                                                  │    │   │
│  │  │  • Schema validation                             │    │   │
│  │  │  • Versioning                                    │    │   │
│  │  │  • Roundtrip testing                             │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────────────────┼──────────────────────────────┐   │
│  │     TEMPLATE BUILDERS     │                              │   │
│  │  ┌────────────────────────▼─────────────────────────┐    │   │
│  │  │         Circuit Factories                        │    │   │
│  │  │                                                  │    │   │
│  │  │  BJTAmplifierBuilder  ──→ Circuit                │    │   │
│  │  │  OpAmpAmplifierBuilder ─→ Circuit                │    │   │
│  │  │                                                  │    │   │
│  │  │  • Parametric config                             │    │   │
│  │  │  • Auto-calculation                              │    │   │
│  │  │  • Standard values (E12/E24)                     │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────────────────┼──────────────────────────────┐   │
│  │     EXPORT LAYER          │  (Future)                    │   │
│  │  ┌────────────────────────▼─────────────────────────┐    │   │
│  │  │         KiCadExporter                            │    │   │
│  │  │                                                  │    │   │
│  │  │  Circuit ──→ Netlist (.net)                      │    │   │
│  │  │  Circuit ──→ Schematic (.kicad_sch)              │    │   │
│  │  └──────────────────────────────────────────────────┘    │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
              │                 │                 │
              ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                       INFRASTRUCTURE LAYER                      │
│       ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│       │  Database   │  │  File System│  │  External   │         │
│       │  (Postgres) │  │  (KiCad)    │  │  APIs       │         │
│       └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Data Flow

### **1. Circuit Creation Flow**

```
     User Request
         │
         ▼
┌─────────────────┐
│   AI Parser     │ → Intent: "BJT CE amplifier, gain=20"
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│Template Builder │ → Config: BJTAmplifierConfig(topology="CE", gain=20)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Circuit Entity │ → Circuit(components, nets, ports, constraints)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Rules Engine   │ → Validate: violations = engine.validate(circuit)
└────────┬────────┘
         │
         ├─── ❌ Has Errors ──→ Return violations
         │
         └─── ✅ Valid
                │
                ▼
         ┌─────────────────┐
         │   IR Serialize  │ → JSON for storage/API
         └─────────────────┘
```

### **2. Validation Pipeline**

```
Circuit Entity
    │
    ├─→ Layer 1: Entity Validation
    │   ├─ Component.__post_init__()
    │   ├─ Net.__post_init__()
    │   └─ Circuit.validate_basic()
    │       └─ Structural integrity
    │
    ├─→ Layer 2: Business Rules
    │   ├─ ComponentParameterRule
    │   ├─ PinConnectionRule
    │   ├─ OpAmpPowerRule
    │   ├─ BJTBiasingRule
    │   └─ ... (10 rules total)
    │
    └─→ Output: List[RuleViolation]
        └─ Severity: ERROR | WARNING | INFO
```

### **3. Serialization Flow**

```
Circuit (Entity)
    │
    ├─→ CircuitIRSerializer.build_ir()
    │       └─→ CircuitIR(circuit, meta, intent_snapshot)
    │
    ├─→ CircuitIRSerializer.to_dict()
    │       └─→ Dict (JSON-compatible)
    │
    ├─→ JSON.stringify() / Storage
    │
    │   ═══════════════════════
    │
    ├─→ JSON.parse() / Load
    │
    ├─→ CircuitIRSerializer.from_dict()
    │       └─→ CircuitIR
    │
    └─→ CircuitIRSerializer.to_circuit()
            └─→ Circuit (Entity)
```

---

## 🧩 Component Relationships

### **Entity Hierarchy**

```
Circuit (Aggregate Root)
│
├─ components: Dict[str, Component]
│  └─ Component
│     ├─ id: str
│     ├─ type: ComponentType (enum)
│     ├─ pins: Tuple[str, ...]
│     └─ parameters: Dict[str, ParameterValue]
│
├─ nets: Dict[str, Net]
│  └─ Net
│     ├─ name: str
│     └─ connected_pins: Tuple[PinRef, ...]
│        └─ PinRef(component_id, pin_name)
│
├─ ports: Dict[str, Port]
│  └─ Port
│     ├─ name: str
│     ├─ net_name: str
│     └─ direction: PortDirection (enum)
│
└─ constraints: Dict[str, Constraint]
   └─ Constraint
      ├─ name: str
      ├─ value: float | str
      └─ unit: Optional[str]
```

### **Rule Engine Structure**

```
CircuitRulesEngine
│
├─ rules: List[CircuitRule]
│  ├─ ComponentParameterRule
│  ├─ PinConnectionRule
│  ├─ GroundReferenceRule
│  ├─ OpAmpPowerRule
│  ├─ BJTBiasingRule
│  ├─ NetSingleConnectionRule
│  ├─ ConstraintFeasibilityRule
│  ├─ PortDirectionRule
│  ├─ ComponentUniqueIdRule
│  └─ CircuitTopologyRule
│
├─ validate(circuit) → List[RuleViolation]
│
└─ RuleViolation
   ├─ rule_name: str
   ├─ message: str
   ├─ severity: ViolationSeverity (ERROR|WARNING|INFO)
   ├─ component_id: Optional[str]
   ├─ net_name: Optional[str]
   └─ details: Dict[str, Any]
```

---

## 📊 Class Diagram (Simplified)

```
┌─────────────────────────────────────────────────────────────┐
│                         <<enum>>                            │
│                      ComponentType                          │
├─────────────────────────────────────────────────────────────┤
│ + RESISTOR, CAPACITOR, INDUCTOR                             │
│ + BJT, MOSFET, OPAMP, DIODE                                 │
│ + VOLTAGE_SOURCE, CURRENT_SOURCE, GROUND                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    <<value object>>                         │
│                      ParameterValue                         │
├─────────────────────────────────────────────────────────────┤
│ + value: int | float | str                                  │
│ + unit: Optional[str]                                       │
├─────────────────────────────────────────────────────────────┤
│ + __post_init__()                                           │
│ + to_dict() → dict                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                       <<entity>>                            │
│                        Component                            │
├─────────────────────────────────────────────────────────────┤
│ + id: str                                                   │
│ + type: ComponentType                                       │
│ + pins: Tuple[str, ...]                                     │
│ + parameters: Dict[str, ParameterValue]                     │
├─────────────────────────────────────────────────────────────┤
│ + __post_init__()  # validates by type                      │
│ + to_dict() → dict                                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    <<aggregate root>>                       │
│                         Circuit                             │
├─────────────────────────────────────────────────────────────┤
│ + name: str                                                 │
│ - _components: Dict[str, Component]                         │
│ - _nets: Dict[str, Net]                                     │
│ - _ports: Dict[str, Port]                                   │
│ - _constraints: Dict[str, Constraint]                       │
│ + components: MappingProxyType (read-only)                  │
│ + nets: MappingProxyType                                    │
│ + ports: MappingProxyType                                   │
│ + constraints: MappingProxyType                             │
├─────────────────────────────────────────────────────────────┤
│ + validate_basic()                                          │
│ + get_component(id) → Optional[Component]                   │
│ + get_net(name) → Optional[Net]                             │
│ + with_component(comp) → Circuit  # immutable builder       │
│ + to_dict() → dict                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 🎯 Design Patterns Used

### **1. Aggregate Pattern**
```
Circuit = Aggregate Root
├─ Controls access to Component, Net, Port, Constraint
├─ Ensures invariants (validate_basic)
└─ Provides MappingProxyType for read-only access
```

### **2. Value Object Pattern**
```
ParameterValue
├─ Immutable (frozen=True)
├─ No identity (equality by value)
└─ Used in Component parameters
```

### **3. Builder Pattern**
```
BJTAmplifierBuilder
├─ config: BJTAmplifierConfig
├─ build() → Circuit
├─ _create_components()
├─ _create_nets()
└─ _create_ports()
```

### **4. Strategy Pattern**
```
CircuitRule (interface)
├─ validate(circuit) → List[RuleViolation]
└─ Implementations:
   ├─ ComponentParameterRule
   ├─ PinConnectionRule
   └─ ... (10 rules)
```

### **5. Serializer Pattern**
```
CircuitIRSerializer
├─ to_dict(ir) → Dict
├─ from_dict(data) → CircuitIR
├─ to_circuit(data) → Circuit
└─ validate_schema(data) → List[str]
```

---

## 🔐 Immutability Strategy

### **Why Immutable?**
1. **Thread-safe** by default
2. **Predictable** state
3. **Easy to reason** about
4. **Cache-friendly**
5. **Prevents bugs** from accidental mutations

### **How Enforced?**

```python
@dataclass(frozen=True)  # ← Makes class immutable
class Circuit:
    _components: Dict[str, Component] = field(default_factory=dict)
    
    def __post_init__(self):
        # Convert internal dict to read-only proxy
        object.__setattr__(
            self, 
            "components",
            MappingProxyType(self._components)
        )
```

### **Update Pattern**

```python
# ❌ Can't mutate directly
circuit.components["R1"] = new_resistor  # TypeError!

# ✅ Create new instance
new_circuit = circuit.with_component(new_resistor)
```

---

## 📈 Scalability Considerations

### **Current Limits**

| Metric | Current | Target (Phase 2) |
|--------|---------|------------------|
| Max components | ~100 | 1000+ |
| Max nets | ~200 | 2000+ |
| Validation time | <50ms | <100ms |
| Serialization | <10ms | <20ms |

### **Optimization Strategies**

1. **Caching**: Component-nets mapping
2. **Lazy validation**: Validate on demand
3. **Parallel rules**: ThreadPoolExecutor
4. **Incremental validation**: Only validate changed parts

---

## 🧪 Testing Strategy

### **Test Pyramid**

```
        ┌─────────────┐
        │     E2E     │  ← Full workflow tests (10%)
        └─────────────┘
       ┌───────────────┐
       │  Integration  │  ← Multi-module tests (30%)
       └───────────────┘
     ┌───────────────────┐
     │   Unit Tests      │  ← Single function tests (60%)
     └───────────────────┘
```

### **Coverage Goals**

- **Unit tests**: 80%+ coverage
- **Integration tests**: Critical paths
- **E2E tests**: Main workflows

---

*Generated: 2026-01-10*  
*See also: [DOMAIN_EVALUATION.md](DOMAIN_EVALUATION.md)*
