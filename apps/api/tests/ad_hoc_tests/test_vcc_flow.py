
from app.domains.circuits.ai_core.parameter_solver import ParameterSolver

s = ParameterSolver()
meta = {"solver_hints": {"num_stages": 2}, "vcc": 24.0}
res = s.solve(target_gain=350, family="multi_stage", metadata=meta)
print(res.values)

