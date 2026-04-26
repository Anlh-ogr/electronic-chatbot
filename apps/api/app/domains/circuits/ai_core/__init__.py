# app/domains/circuits/ai_core/__init__.py
""" AI Core Module - Circuit Grammar-based AI Engine

Hệ thống AI Core hoạt động theo 4 bước:
 step1: NLPSpecParser   — parse yêu cầu user → JSON spec
 step2: TopologyPlanner — chọn/ghép block topology
 step3: ParameterSolver — giải tham số (gain, R, C...)
 step4: CircuitGenerator — sinh circuit IR + validate domain

Cấp 1 (thesis): chọn template gần nhất + solve + đề xuất mở rộng
Cấp 2 (tương lai): tự synthesis topology mới từ block graph
"""


from .spec_parser import NLPSpecParser, UserSpec
from .metadata_repo import MetadataRepository
from .topology_planner import TopologyPlanner, TopologyPlan
from .llm_topology_selector import LLMTopologySelector, select_topology
from .llm_topology_rules import TopologyRuleEngine
from .parameter_solver import ParameterSolver, SolvedParams
from .circuit_generator import CircuitGenerator, GeneratedCircuit
from .ai_core import AICore, PipelineResult

""" Lý do sử dụng thư viện
.spec_parser: chuyển ngôn ngữ tự nhiên → spec cấu trúc JSON
.metadata_repo: lưu trữ kiến thức mạch điện dưới dạng blocks
.topology_planner: chọn/ghép block topology phù hợp spec
.parameter_solver: giải tham số mạch (gain, R, C...) theo spec
.circuit_generator: sinh circuit IR từ topology + tham số
.ai_core: lớp tổng hợp, điều phối các bước xử lý AI Core
"""


__all__ = [
    "AICore",
    "NLPSpecParser",
    "UserSpec",
    "MetadataRepository",
    "TopologyPlanner",
    "TopologyPlan",
    "LLMTopologySelector",
    "TopologyRuleEngine",
    "select_topology",
    "ParameterSolver",
    "SolvedParams",
    "CircuitGenerator",
    "GeneratedCircuit",
]
