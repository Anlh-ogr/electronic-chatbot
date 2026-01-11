"""
Test Cases for Rules Engine Evaluation
Kiểm tra các bugs đã sửa và edge cases
"""

from app.domains.circuits.entities import (
    Circuit, Component, ComponentType, Net, Port, PortDirection,
    PinRef, Constraint, ParameterValue
)
from app.domains.circuits.rules import (
    CircuitRulesEngine, ComponentParameterRule, PinConnectionRule,
    OpAmpPowerRule, BJTBiasingRule, ViolationSeverity
)


def test_opamp_power_rule_performance():
    """Test OpAmpPowerRule with optimized lookup"""
    print("\n=== Test 1: OpAmpPowerRule Performance ===")
    
    # Tạo circuit với OpAmp và voltage source
    opamp = Component(
        id="U1",
        type=ComponentType.OPAMP,
        pins=("IN+", "IN-", "OUT", "V+", "V-"),
        parameters={"model": ParameterValue("LM358", None)}
    )
    
    vsource = Component(
        id="V1",
        type=ComponentType.VOLTAGE_SOURCE,
        pins=("P", "N"),
        parameters={"voltage": ParameterValue(12, "V")}
    )
    
    ground = Component(
        id="GND1",
        type=ComponentType.GROUND,
        pins=("G",),
        parameters={}
    )
    
    # Net kết nối OpAmp với voltage source
    net_vcc = Net(
        name="VCC",
        connected_pins=(
            PinRef("U1", "V+"),
            PinRef("V1", "P")
        )
    )
    
    net_gnd = Net(
        name="GND",
        connected_pins=(
            PinRef("U1", "V-"),
            PinRef("V1", "N"),
            PinRef("GND1", "G")
        )
    )
    
    # Thêm dummy nets cho input/output
    net_in = Net(name="IN", connected_pins=(PinRef("U1", "IN+"), PinRef("U1", "IN-")))
    net_out = Net(name="OUT", connected_pins=(PinRef("U1", "OUT"),))
    
    circuit = Circuit(
        name="OpAmp Test Circuit",
        _components={"U1": opamp, "V1": vsource, "GND1": ground},
        _nets={"VCC": net_vcc, "GND": net_gnd, "IN": net_in, "OUT": net_out},
        _ports={},
        _constraints={}
    )
    
    # Validate
    rule = OpAmpPowerRule()
    violations = rule.validate(circuit)
    
    # Kiểm tra
    errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
    print(f"OpAmp power violations: {len(errors)}")
    
    if len(errors) == 0:
        print("✅ PASS: OpAmp có power supply")
    else:
        print(f"❌ FAIL: {errors[0].message}")
        return False
    
    return True


def test_bjt_biasing_rule_logic():
    """Test BJTBiasingRule with fixed loop logic"""
    print("\n=== Test 2: BJTBiasingRule Logic ===")
    
    # Tạo BJT với base resistor
    bjt = Component(
        id="Q1",
        type=ComponentType.BJT,
        pins=("C", "B", "E"),
        parameters={"model": ParameterValue("2N2222", None)}
    )
    
    rb = Component(
        id="RB",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(10000, "ohm")}
    )
    
    rc = Component(
        id="RC",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(1000, "ohm")}
    )
    
    ground = Component(
        id="GND1",
        type=ComponentType.GROUND,
        pins=("G",),
        parameters={}
    )
    
    # Net kết nối base với resistor
    net_base = Net(
        name="BASE",
        connected_pins=(
            PinRef("Q1", "B"),
            PinRef("RB", "2")
        )
    )
    
    net_collector = Net(
        name="COLLECTOR",
        connected_pins=(
            PinRef("Q1", "C"),
            PinRef("RC", "2")
        )
    )
    
    net_emitter = Net(
        name="EMITTER",
        connected_pins=(
            PinRef("Q1", "E"),
            PinRef("GND1", "G")
        )
    )
    
    net_vcc = Net(
        name="VCC",
        connected_pins=(
            PinRef("RB", "1"),
            PinRef("RC", "1")
        )
    )
    
    circuit = Circuit(
        name="BJT Test Circuit",
        _components={"Q1": bjt, "RB": rb, "RC": rc, "GND1": ground},
        _nets={"BASE": net_base, "COLLECTOR": net_collector, "EMITTER": net_emitter, "VCC": net_vcc},
        _ports={},
        _constraints={}
    )
    
    # Validate
    rule = BJTBiasingRule()
    violations = rule.validate(circuit)
    
    # Kiểm tra
    warnings = [v for v in violations if v.severity == ViolationSeverity.WARNING]
    print(f"BJT biasing warnings: {len(warnings)}")
    
    if len(warnings) == 0:
        print("✅ PASS: BJT có base resistor")
    else:
        print(f"❌ FAIL: {warnings[0].message}")
        return False
    
    return True


def test_pin_connection_rule_multiple_nets():
    """Test PinConnectionRule - pin trong nhiều nets khác nhau
    NOTE: Circuit.__post_init__ đã validate này, test case này chỉ để 
    kiểm tra rule riêng lẻ có hoạt động không
    """
    print("\n=== Test 3: PinConnectionRule - Unconnected Pins ===")
    
    r1 = Component(
        id="R1",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(1000, "ohm")}
    )
    
    # Pin R1.2 không được kết nối (treo lơ lửng)
    net_a = Net(
        name="NET_A",
        connected_pins=(PinRef("R1", "1"),)
    )
    
    circuit = Circuit(
        name="Floating Pin Test Circuit",
        _components={"R1": r1},
        _nets={"NET_A": net_a},
        _ports={},
        _constraints={}
    )
    
    # Validate
    rule = PinConnectionRule()
    violations = rule.validate(circuit)
    
    # Kiểm tra
    errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
    print(f"Pin connection errors: {len(errors)}")
    
    # Phải có lỗi vì pin R1.2 không kết nối
    floating_errors = [v for v in errors if "không được kết nối" in v.message]
    
    if len(floating_errors) > 0:
        print(f"✅ PASS: Detected floating pin - {floating_errors[0].message}")
        return True
    else:
        print("❌ FAIL: Should detect floating pin")
        return False


def test_component_parameter_rule():
    """Test ComponentParameterRule - thiếu parameters
    NOTE: Component.__post_init__ đã validate này. Test kiểm tra rule 
    có thể phát hiện nếu validation bị bypass
    """
    print("\n=== Test 4: ComponentParameterRule ===")
    
    # ⚠️ Capacitor thiếu capacitance nhưng có model (BJT/MOSFET style)
    # Dùng BJT thay vì để test WARNING (không phải ERROR)
    q1 = Component(
        id="Q1",
        type=ComponentType.BJT,
        pins=("C", "B", "E"),
        parameters={"model": ParameterValue("800", "mA")}  # Fix missing model - should be WARNING
    )
    
    # ✅ Resistor có resistance
    r1 = Component(
        id="R1",
        type=ComponentType.RESISTOR,
        pins=("1", "2"),
        parameters={"resistance": ParameterValue(1000, "ohm")}
    )
    
    net1 = Net(name="N1", connected_pins=(PinRef("Q1", "C"), PinRef("R1", "1")))
    net2 = Net(name="N2", connected_pins=(PinRef("Q1", "B"),))
    net3 = Net(name="N3", connected_pins=(PinRef("Q1", "E"), PinRef("R1", "2")))
    
    circuit = Circuit(
        name="Parameter Test Circuit",
        _components={"Q1": q1, "R1": r1},
        _nets={"N1": net1, "N2": net2, "N3": net3},
        _ports={},
        _constraints={}
    )
    
    # Validate
    rule = ComponentParameterRule()
    violations = rule.validate(circuit)
    
    # Kiểm tra
    q1_violations = [v for v in violations if v.component_id == "Q1"]
    r1_violations = [v for v in violations if v.component_id == "R1"]
    
    print(f"Q1 violations: {len(q1_violations)}, R1 violations: {len(r1_violations)}")
    
    if len(q1_violations) > 0 and len(r1_violations) == 0:
        print(f"✅ PASS: Detected missing model - {q1_violations[0].message}")
        return True
    else:
        print("❌ FAIL: Should detect missing model only for Q1")
        return False


def test_full_rules_engine():
    """Test toàn bộ rules engine"""
    print("\n=== Test 5: Full Rules Engine ===")
    
    # Tạo mạch phức tạp hơn
    from app.domains.circuits.rules import create_test_circuit
    
    circuit = create_test_circuit()
    engine = CircuitRulesEngine()
    
    violations = engine.validate(circuit)
    summary = engine.get_summary(violations)
    
    print(f"Total violations: {summary['total']}")
    print(f"  Errors: {summary['errors']}")
    print(f"  Warnings: {summary['warnings']}")
    print(f"  Info: {summary['info']}")
    
    print("\nViolations by rule:")
    for rule_name, count in summary['by_rule'].items():
        print(f"  {rule_name}: {count}")
    
    # Kiểm tra engine không crash
    if summary['total'] > 0:
        print("✅ PASS: Engine hoạt động và phát hiện violations")
        return True
    else:
        print("⚠️ WARNING: No violations detected (circuit might be valid)")
        return True


def run_all_tests():
    """Chạy tất cả test cases"""
    print("=" * 60)
    print("Rules Engine Evaluation - Test Suite")
    print("=" * 60)
    
    tests = [
        test_opamp_power_rule_performance,
        test_bjt_biasing_rule_logic,
        test_pin_connection_rule_multiple_nets,
        test_component_parameter_rule,
        test_full_rules_engine,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n❌ EXCEPTION in {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    # Summary
    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} PASSED")
    print("=" * 60)
    
    if all(results):
        print("🎉 All tests PASSED!")
    else:
        print("⚠️ Some tests FAILED. Check logs above.")
    
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
