from pathlib import Path
import types
import sys
import pathlib
# Ensure repo root is on sys.path so 'app' package imports resolve
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))  # repo root

# Import module by path to avoid package resolution issues
import importlib.util
module_path = r'D:\Work\thesis\electronic-chatbot\apps\api\app\application\circuits\use_cases\export_kicad_sch.py'
spec = importlib.util.spec_from_file_location('export_kicad_sch', module_path)
export_kicad_sch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_kicad_sch)
ExportKiCadSchUseCase = export_kicad_sch.ExportKiCadSchUseCase


# Minimal fake component object
class FakeComp:
    def __init__(self, ref_id, type_, value, kicad_symbol=None, footprint=""):
        self.ref_id = ref_id
        self.type = type_
        self.value = value
        self.kicad_symbol = kicad_symbol
        self.footprint = footprint

# Minimal fake net object
class FakeNet:
    def __init__(self, nodes):
        self.nodes = nodes


def main():
    exporter = ExportKiCadSchUseCase(repository=None, exporter=None, storage_path=Path('.'))

    vcc = FakeComp('VCC', 'power_symbol', 'VCC')
    gnd = FakeComp('GND', 'power_symbol', 'GND')
    r1 = FakeComp('R1', 'resistor', '10k')

    # Nets: connect VCC to R1 pin 1; GND to R1 pin 2
    net1 = FakeNet(['VCC:1', 'R1:1'])
    net2 = FakeNet(['GND:1', 'R1:2'])

    ir = types.SimpleNamespace(components=[vcc, gnd, r1], nets=[net1, net2])

    sch = exporter.compile_to_sch(ir)
    print(sch)

    # Quick checks
    has_pin1 = '(pin "1"' in sch
    print('\nHAS_PIN_1:', has_pin1)

    # Ensure each power symbol has a closing ')'
    count_power = sch.count('(lib_id "power:VCC")') + sch.count('(lib_id "power:GND")')
    print('POWER_SYMBOL_COUNT:', count_power)

if __name__ == '__main__':
    main()
