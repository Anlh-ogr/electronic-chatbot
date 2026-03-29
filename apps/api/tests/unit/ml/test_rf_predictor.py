import sys
from pathlib import Path
sys.path.insert(0, str(Path('thesis/electronic-chatbot/apps/api').resolve()))
from app.domains.circuits.ai_core.ml_topology_selector import RandomForestTopologySelector
from app.domains.circuits.ai_core.spec_parser import UserSpec

selector = RandomForestTopologySelector(model_dir=Path('thesis/electronic-chatbot/apps/api/resources/ml_models'))

class MockSpec:
    gain = 120.0
    frequency = 12e3
    input_channels = 1
    high_cmr = True
    input_mode = "single_ended"
    output_buffer = False
    power_output = False
    supply_mode = "auto"
    coupling_preference = "auto"
    device_preference = "opamp"
    extra_requirements = []
    vcc = 12.0

spec = MockSpec()
print(selector.predict_topologies(spec))
