from app.domains.circuits.ai_core.parameter_solver import ParameterSolver


def test_cb_solver_targets_requested_gain() -> None:
    solver = ParameterSolver(preferred_series="E24")
    solved = solver.solve(
        target_gain=8.0,
        family="common_base",
        metadata={"vcc": 12.0, "solver_hints": {"ic_ma": 1.0}},
    )
    assert solved.success
    assert solved.actual_gain is not None
    assert abs(solved.actual_gain - 8.0) / 8.0 * 100.0 < 15.0
