# 📋 Domain System - Action Items

**Generated**: 2026-01-11 23:30  
**Status**: Phase 1 @ 88% completion

---

## 🔴 Priority 0: CRITICAL (This Week)

### 1. File Cleanup ✅ COMPLETED
- [x] Delete `factories.py` (empty, redundant with template_builder.py)
- [x] Delete `serializers.py` (empty, redundant with ir.py)  
- [x] Move `templates.py` → `backup/templates.py.bak`
- [x] Add to `.gitignore`: `**/backup/`, `**/*.bak`

**Commands**:
```bash
cd apps/api/app/domains/circuits
rm factories.py serializers.py
mkdir -p backup
mv templates.py backup/templates.py.bak
```

### 2. Fix Failing Test
- [ ] Fix `test_component_parameter_rule` in test_rules_evaluation.py
- [ ] Options:
  - A) Relax BJT model validation in entities.py (make WARNING not ERROR)
  - B) Change test to use different component type
  - C) Mock entity validation in test

**File**: `tests/domain/test_rules_evaluation.py:236`

---

## 🟡 Priority 1: HIGH (Next 2 Weeks)

### 3. Increase Test Coverage (62% → 75%) ✅ 88% COMPLETE

#### Template Builder Tests ✅ COMPLETE
- [x] `test_bjt_amplifier_ce_topology()` ✅
- [x] `test_bjt_amplifier_cc_topology()` ✅
- [x] `test_bjt_amplifier_cb_topology()` ✅
- [x] `test_opamp_inverting()` ✅
- [x] `test_opamp_non_inverting()` ✅
- [x] `test_opamp_differential()` ✅
- [x] `test_component_calculator_e12_rounding()` ✅

#### Integration Tests ✅ CREATED (6/17 passing)
- [x] `test_full_workflow_bjt_amplifier()` ⚠️
- [x] `test_template_to_ir_to_circuit()` ⚠️
- [ ] `test_rules_validation_on_generated_circuits()`

#### Edge Case Tests
- [ ] `test_circuit_with_1000_components()` (performance)
- [ ] `test_invalid_net_references()`
- [ ] `test_circular_dependencies()` (should not exist)

**Goal**: 80%+ coverage across all modules

### 4. Documentation

- [ ] Create `docs/architecture.md` - System architecture overview
- [ ] Create `docs/api_reference.md` - Public API documentation
- [ ] Create `docs/template_guide.md` - How to use template builders
- [ ] Update README with domain layer explanation
- [ ] Add docstrings to all public methods (if missing)

### 5. Extract Hard-coded Values

#### rules.py
```python
# Current: Magic numbers
if constraint.name == "gain" and constraint.value > 1000:
    ...

# Proposed: Config-driven
@dataclass
class RuleThresholds:
    max_gain: float = 1000.0
    max_supply_voltage: float = 50.0
    max_current: float = 10.0
    
class ConstraintFeasibilityRule(CircuitRule):
    def __init__(self, thresholds: RuleThresholds = None):
        self.thresholds = thresholds or RuleThresholds()
```

#### template_builder.py
```python
# Current: Hard-coded models
bjt_model: str = "2N3904"
opamp_model: str = "LM741"

# Proposed: Model registry
@dataclass
class ComponentLibrary:
    bjt_models: List[str] = ["2N3904", "2N2222", "BC547"]
    opamp_models: List[str] = ["LM741", "LM358", "TL071"]
    
    def get_default_bjt(self) -> str:
        return self.bjt_models[0]
```

**Files to update**:
- [ ] `rules.py` - Extract thresholds
- [ ] `template_builder.py` - Create component library

---

## 🟢 Priority 2: MEDIUM (Month 2)

### 6. Implement KiCad Exporter

- [ ] Research KiCad netlist format
- [ ] Implement `KiCadNetlistExporter` class
- [ ] Implement `KiCadSchematicExporter` class
- [ ] Create component symbol mapping
- [ ] Add tests for KiCad export
- [ ] Documentation for KiCad workflow

**New file**: `kicad_exporter.py`

**API**:
```python
class KiCadNetlistExporter:
    @staticmethod
    def export(circuit: Circuit) -> str:
        """Circuit → KiCad netlist (.net)"""
        ...

class KiCadSchematicExporter:
    @staticmethod  
    def export(circuit: Circuit, library: SymbolLibrary) -> str:
        """Circuit → KiCad schematic (.kicad_sch)"""
        ...
```

### 7. Expand Template Library

#### Oscillators
- [ ] `555TimerOscillatorBuilder` - Astable/monostable
- [ ] `RCOscillatorBuilder` - Phase shift oscillator
- [ ] `LCOscillatorBuilder` - Colpitts/Hartley
- [ ] `CrystalOscillatorBuilder` - Crystal oscillator

#### Filters
- [ ] `PassiveFilterBuilder` - RC/RL filters
- [ ] `ActiveFilterBuilder` - Sallen-Key, MFB
- [ ] `ButterworthFilterBuilder` - LP/HP/BP
- [ ] `ChebyshevFilterBuilder`

#### Power Supplies
- [ ] `LinearRegulatorBuilder` - 78xx/79xx series
- [ ] `VoltageReferenceBuilder` - Zener, bandgap
- [ ] `SwitchingPSUBuilder` - Buck/boost converters

**Goal**: 15+ circuit templates by end of Phase 2

### 8. Performance Optimization

- [ ] Benchmark with 1000+ component circuits
- [ ] Profile rules engine performance
- [ ] Cache component-nets mapping in Circuit
- [ ] Lazy validation option (validate on demand)
- [ ] Parallel rule execution (if needed)

**Target**: <50ms validation for 1000-component circuit

---

## 🔵 Priority 3: LOW (Month 3+)

### 9. Phase 2 Rules - Electrical Analysis

- [ ] `VoltageDropRule` - Check voltage drops
- [ ] `CurrentLimitRule` - Component current ratings
- [ ] `PowerDissipationRule` - Thermal analysis
- [ ] `FrequencyResponseRule` - Bode plots
- [ ] `StabilityRule` - Phase/gain margins
- [ ] `NoiseAnalysisRule` - SNR calculations

### 10. Advanced Features

- [ ] SPICE simulation integration (ngspice)
- [ ] Multi-stage amplifier support
- [ ] Feedback network analysis
- [ ] Parameter sweep optimization
- [ ] AI-driven component selection

### 11. Quality Improvements

- [ ] Add Architecture Decision Records (ADR)
- [ ] Set up CI/CD for domain tests
- [ ] Code coverage reporting (Codecov)
- [ ] Static analysis (mypy strict mode)
- [ ] Security audit (Bandit)

---

## 📊 Progress Tracking

### Current Status

```
Phase 1 Completion:    ████████░░  85%
Test Coverage:         ██████░░░░  62%
Documentation:         ███████░░░  70%
Production Readiness:  ████████░░  85%
```

### Milestones

- [ ] **Week 1**: Priority 0 complete (cleanup)
- [ ] **Week 2-3**: Priority 1 at 50% (tests + docs)
- [ ] **Week 4**: Priority 1 at 100% (ready for review)
- [ ] **Month 2**: Priority 2 at 50% (KiCad + templates)
- [ ] **Month 3**: Phase 2 planning complete

---

## 🎯 Success Criteria

### Phase 1 Sign-off Criteria

✅ **Must Have**:
- [x] No critical bugs in core domain
- [x] All core entities implemented
- [x] Rules engine functional
- [x] IR serialization working
- [ ] Test coverage ≥ 80%
- [ ] Documentation complete
- [ ] No empty placeholder files

⭐ **Nice to Have**:
- [ ] KiCad exporter working
- [ ] 10+ circuit templates
- [ ] Performance benchmarks
- [ ] CI/CD pipeline

### Definition of Done

A task is "done" when:
1. ✅ Code implemented and reviewed
2. ✅ Unit tests written and passing
3. ✅ Integration tests (if applicable)
4. ✅ Documentation updated
5. ✅ No lint/type errors
6. ✅ Peer reviewed (if in team)

---

## 📞 Resources

### Documentation
- [DOMAIN_EVALUATION.md](DOMAIN_EVALUATION.md) - Full assessment
- [RULES_EVALUATION.md](RULES_EVALUATION.md) - Rules engine analysis
- [RULES_SUMMARY.md](RULES_SUMMARY.md) - Rules quick reference

### Related Files
- [entities.py](../../apps/api/app/domains/circuits/entities.py) - Core domain entities
- [rules.py](../../apps/api/app/domains/circuits/rules.py) - Business rules engine
- [ir.py](../../apps/api/app/domains/circuits/ir.py) - Serialization layer
- [template_builder.py](../../apps/api/app/domains/circuits/template_builder.py) - Circuit generators

### External Resources
- KiCad File Formats: https://dev-docs.kicad.org/en/file-formats/
- SPICE Netlist: http://ngspice.sourceforge.net/docs.html
- DDD Patterns: https://martinfowler.com/bliki/DomainDrivenDesign.html

---

*Last Updated: 2026-01-10*  
*Next Review: 2026-01-17 (Weekly)*
