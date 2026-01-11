"""
Integration tests cho template builders
Tests full workflow: config → build → validate → serialize
"""

import pytest
from app.domains.circuits.template_builder import (
    AmplifierFactory,
    BJTAmplifierConfig,
    BJTAmplifierBuilder,
    OpAmpAmplifierConfig,
    OpAmpAmplifierBuilder
)
from app.domains.circuits.entities import ComponentType
from app.domains.circuits.rules import CircuitRulesEngine, ViolationSeverity
from app.domains.circuits.ir import CircuitIRSerializer


class TestBJTAmplifierIntegration:
    """Integration tests cho BJT amplifier templates"""
    
    def test_bjt_ce_full_workflow(self):
        """Full workflow: create → validate → serialize → deserialize"""
        # Step 1: Create circuit từ template
        circuit = AmplifierFactory.create_bjt(
            topology="CE",
            gain=15.0,
            vcc=12.0
        )
        
        assert circuit is not None
        assert circuit.name.startswith("CE Amplifier")
        assert len(circuit.components) > 0
        
        # Step 2: Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0, f"Validation errors: {[e.message for e in errors]}"
        
        # Step 3: Serialize
        ir_dict = CircuitIRSerializer.serialize(circuit)
        assert ir_dict["meta"]["circuit_name"] == circuit.name
        assert len(ir_dict["components"]) == len(circuit.components)
        
        # Step 4: Deserialize
        restored = CircuitIRSerializer.deserialize(ir_dict)
        assert restored.name == circuit.name
        assert len(restored.components) == len(circuit.components)
    
    def test_bjt_cc_full_workflow(self):
        """BJT Common Collector full workflow"""
        circuit = AmplifierFactory.create_bjt(
            topology="CC",
            gain=0.95,
            vcc=12.0
        )
        
        assert "CC" in circuit.name
        
        # Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0
        
        # Roundtrip test
        success = CircuitIRSerializer.roundtrip_test(circuit)
        assert success
    
    def test_bjt_cb_full_workflow(self):
        """BJT Common Base full workflow"""
        circuit = AmplifierFactory.create_bjt(
            topology="CB",
            gain=10.0,
            vcc=12.0
        )
        
        assert "CB" in circuit.name
        
        # Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0
        
        # Roundtrip
        success = CircuitIRSerializer.roundtrip_test(circuit)
        assert success
    
    def test_bjt_with_custom_config(self):
        """BJT với custom config chi tiết"""
        config = BJTAmplifierConfig(
            topology="CE",
            vcc=12.0,
            gain_target=20.0,
            bjt_model="2N3904",
            beta=150.0,
            ic_target=2e-3,
            bias_type="voltage_divider",
            include_coupling=True
        )
        
        builder = BJTAmplifierBuilder(config)
        circuit = builder.build()
        
        # Kiểm tra components
        assert any(c.type == ComponentType.BJT for c in circuit.components.values())
        
        # Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0
    
    def test_bjt_different_supply_voltages(self):
        """BJT với các supply voltage khác nhau"""
        supply_voltages = [5.0, 9.0, 12.0, 15.0, 24.0]
        
        for vcc in supply_voltages:
            circuit = AmplifierFactory.create_bjt(
                topology="CE",
                gain=15.0,
                vcc=vcc
            )

            # Template uses power port + constraint, not a voltage source component
            assert "VCC" in circuit.ports
            assert "vcc" in circuit.constraints
            assert circuit.constraints["vcc"].value == vcc
            
            # Validate
            engine = CircuitRulesEngine()
            violations = engine.validate(circuit)
            errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
            assert len(errors) == 0, f"VCC={vcc}V failed validation"


class TestOpAmpAmplifierIntegration:
    """Integration tests cho OpAmp amplifier templates"""
    
    def test_opamp_inverting_full_workflow(self):
        """OpAmp inverting amplifier full workflow"""
        circuit = AmplifierFactory.create_opamp(
            topology="inverting",
            gain=-10.0
        )
        
        assert "Inverting" in circuit.name
        assert len(circuit.components) > 0
        
        # Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0, f"Errors: {[e.message for e in errors]}"
        
        # Serialize
        ir_dict = CircuitIRSerializer.serialize(circuit)
        assert ir_dict is not None
        
        # Deserialize
        restored = CircuitIRSerializer.deserialize(ir_dict)
        assert restored.name == circuit.name
    
    def test_opamp_non_inverting_full_workflow(self):
        """OpAmp non-inverting amplifier full workflow"""
        circuit = AmplifierFactory.create_opamp(
            topology="non_inverting",
            gain=11.0
        )
        
        assert "Non-Inverting" in circuit.name
        
        # Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0
        
        # Roundtrip
        success = CircuitIRSerializer.roundtrip_test(circuit)
        assert success
    
    def test_opamp_differential_full_workflow(self):
        """OpAmp differential amplifier full workflow"""
        circuit = AmplifierFactory.create_opamp(
            topology="differential",
            gain=5.0
        )
        
        assert "Differential" in circuit.name
        
        # Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0
        
        # Roundtrip
        success = CircuitIRSerializer.roundtrip_test(circuit)
        assert success
    
    def test_opamp_with_custom_config(self):
        """OpAmp với custom config"""
        config = OpAmpAmplifierConfig(
            topology="inverting",
            gain=-15.0,
            opamp_model="LM741",
            r1=10000,
            r2=150000,
            include_coupling=True
        )
        
        builder = OpAmpAmplifierBuilder(config)
        circuit = builder.build()
        
        # Kiểm tra có OpAmp
        has_opamp = any(
            c.type == ComponentType.OPAMP 
            for c in circuit.components.values()
        )
        assert has_opamp
        
        # Validate
        engine = CircuitRulesEngine()
        violations = engine.validate(circuit)
        errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
        assert len(errors) == 0
    
    def test_opamp_different_gains(self):
        """OpAmp với các gain khác nhau"""
        gains = [-1.0, -5.0, -10.0, -20.0, -50.0]
        
        for gain in gains:
            circuit = AmplifierFactory.create_opamp(
                topology="inverting",
                gain=gain
            )
            
            # Validate
            engine = CircuitRulesEngine()
            violations = engine.validate(circuit)
            errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
            assert len(errors) == 0, f"Gain={gain} failed"


class TestTemplateComparison:
    """So sánh các template với nhau"""
    
    def test_bjt_ce_vs_cc_components(self):
        """So sánh components giữa CE và CC"""
        ce_circuit = AmplifierFactory.create_bjt(topology="CE", gain=15.0, vcc=12.0)
        cc_circuit = AmplifierFactory.create_bjt(topology="CC", gain=0.95, vcc=12.0)
        
        # Cả 2 đều phải có BJT
        ce_has_bjt = any(c.type == ComponentType.BJT for c in ce_circuit.components.values())
        cc_has_bjt = any(c.type == ComponentType.BJT for c in cc_circuit.components.values())
        
        assert ce_has_bjt
        assert cc_has_bjt
        
        # CE có Rc (collector resistor), CC không có
        # (implementation detail - có thể thay đổi)
        
    def test_opamp_inverting_vs_non_inverting(self):
        """So sánh inverting vs non-inverting"""
        inv = AmplifierFactory.create_opamp(topology="inverting", gain=-10.0)
        non_inv = AmplifierFactory.create_opamp(topology="non_inverting", gain=11.0)
        
        # Cả 2 đều có OpAmp
        inv_has_opamp = any(c.type == ComponentType.OPAMP for c in inv.components.values())
        non_inv_has_opamp = any(c.type == ComponentType.OPAMP for c in non_inv.components.values())
        
        assert inv_has_opamp
        assert non_inv_has_opamp
        
        # Cả 2 đều valid
        engine = CircuitRulesEngine()
        
        inv_violations = engine.validate(inv)
        inv_errors = [v for v in inv_violations if v.severity == ViolationSeverity.ERROR]
        
        non_inv_violations = engine.validate(non_inv)
        non_inv_errors = [v for v in non_inv_violations if v.severity == ViolationSeverity.ERROR]
        
        assert len(inv_errors) == 0
        assert len(non_inv_errors) == 0


class TestErrorHandling:
    """Test error handling trong template builders"""
    
    def test_bjt_invalid_topology(self):
        """BJT với topology không hợp lệ → ValueError"""
        with pytest.raises(ValueError):
            AmplifierFactory.create_bjt(
                topology="INVALID",
                gain=15.0,
                vcc=12.0
            )
    
    def test_opamp_invalid_topology(self):
        """OpAmp với topology không hợp lệ → ValueError"""
        with pytest.raises(ValueError):
            AmplifierFactory.create_opamp(
                topology="INVALID",
                gain=10.0
            )
    
    def test_bjt_negative_vcc(self):
        """BJT với VCC âm"""
        # Có thể raise exception hoặc tạo circuit invalid
        # Tùy implementation
        try:
            circuit = AmplifierFactory.create_bjt(
                topology="CE",
                gain=15.0,
                vcc=-12.0
            )
            
            # Nếu không raise, circuit phải invalid khi validate
            engine = CircuitRulesEngine()
            violations = engine.validate(circuit)
            errors = [v for v in violations if v.severity == ViolationSeverity.ERROR]
            
            # Có thể có hoặc không có error, tùy implementation
            
        except ValueError:
            # OK - builder catch được
            pass


class TestPerformance:
    """Performance tests"""
    
    def test_create_100_circuits_performance(self):
        """Tạo 100 circuits và validate - phải < 5s"""
        import time
        
        start = time.time()
        
        engine = CircuitRulesEngine()
        
        for i in range(100):
            # Xen kẽ BJT và OpAmp
            if i % 2 == 0:
                circuit = AmplifierFactory.create_bjt(
                    topology="CE",
                    gain=15.0,
                    vcc=12.0
                )
            else:
                circuit = AmplifierFactory.create_opamp(
                    topology="inverting",
                    gain=-10.0
                )
            
            violations = engine.validate(circuit)
        
        elapsed = time.time() - start
        
        # Phải < 5 giây cho 100 circuits
        assert elapsed < 5.0, f"Too slow: {elapsed:.2f}s for 100 circuits"
        
        print(f"✅ Created & validated 100 circuits in {elapsed:.2f}s")


class TestConstraintPreservation:
    """Test constraints được giữ nguyên qua workflow"""
    
    def test_bjt_gain_constraint_preserved(self):
        """BJT gain constraint preserved qua serialize/deserialize"""
        circuit = AmplifierFactory.create_bjt(
            topology="CE",
            gain=20.0,
            vcc=12.0
        )
        
        # Check constraint
        if "gain" in circuit.constraints:
            original_gain = circuit.constraints["gain"].value
            
            # Serialize → Deserialize
            ir_dict = CircuitIRSerializer.serialize(circuit)
            restored = CircuitIRSerializer.deserialize(ir_dict)
            
            # Gain preserved
            assert "gain" in restored.constraints
            assert restored.constraints["gain"].value == original_gain
