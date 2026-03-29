from app.domains.circuits.ai_core.parameter_solver import ParameterSolver
from app.domains.validators.dc_bias_validator import ComponentSet, DCBiasValidator
import pprint

solver = ParameterSolver()
res = solver._solve_ce(gain=18.7, meta={"vcc": 24.0, "solver_hints": {"ic_ma": 1.0}})
print(res.values)

c = ComponentSet(
    R1=res.values["R1"],
    R2=res.values["R2"],
    RC=res.values["RC"],
    RE=res.values["RE"], 
    VCC=24.0,
    beta=100.0,
    topology="common_emitter"
)
validator = DCBiasValidator()
res_val = validator.validate(c, gain_target=None)
print("DC PASS:", res_val.passed)
pprint.pprint(res_val.errors)
pprint.pprint(res_val.metrics)

