import pytest
from app.domains.circuits.ai_core.spec_parser import UserSpec
from app.domains.circuits.ai_core.topology_planner import TopologyPlanner, TopologyPlan

def test_topology_planner_gain_under_100():
    planner = TopologyPlanner()
    spec = UserSpec(circuit_type="common_emitter", gain=50.0)
    plan = TopologyPlan()
    
    result = planner._validate_circuit_type(spec, plan)
    
    assert result is True
    assert spec.circuit_type == "common_emitter", "Mạch đơn tầng với gain < 100 không được thay đổi circuit_type"
    assert len(plan.rationale) == 0

def test_topology_planner_gain_over_100():
    planner = TopologyPlanner()
    spec = UserSpec(circuit_type="common_emitter", gain=150.0)
    plan = TopologyPlan()
    
    result = planner._validate_circuit_type(spec, plan)
    
    assert result is True
    assert spec.circuit_type == "multi_stage", "Mạch đơn tầng với gain >= 100 phải được chuyển thành multi_stage"
    assert len(plan.rationale) > 0
    assert "upgrading 'common_emitter' to 'multi_stage'" in plan.rationale[0]

def test_topology_planner_gain_over_100_opamp():
    planner = TopologyPlanner()
    spec = UserSpec(circuit_type="inverting", gain=200.0)
    plan = TopologyPlan()
    
    result = planner._validate_circuit_type(spec, plan)
    
    assert result is True
    assert spec.circuit_type == "multi_stage", "Tất cả các mạch (kể cả Op-Amp) cần nâng lên multi_stage vì vấn đề băng thông và ổn định"
    assert len(plan.rationale) > 0
    assert "upgrading 'inverting' to 'multi_stage'" in plan.rationale[0]

def test_topology_planner_gain_exact_100():
    planner = TopologyPlanner()
    spec = UserSpec(circuit_type="common_source", gain=100.0)
    plan = TopologyPlan()
    
    result = planner._validate_circuit_type(spec, plan)
    
    assert result is True
    assert spec.circuit_type == "multi_stage"
    assert any("upgrading 'common_source'" in r for r in plan.rationale)
