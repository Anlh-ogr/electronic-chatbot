import sys
from pathlib import Path

# Add the parent directory of the `app` module to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.services.circuit_store import CircuitStore
from app.services.formatter import render_circuit_answer

# Load the data into the store object
store = CircuitStore()
store.load()
circuits = store.circuits  # Access circuits from the store object

# Debugging: Print the total number of circuits and their 
if len(circuits) > 0:
    circuit_1 = circuits[0]  # Boost_mt3608
    print("render_circuit_answer for circuit 1:")
    print(render_circuit_answer(circuit_1))
else:
    print("No circuits available for circuit_1.")

if len(circuits) > 3:
    circuit_2 = circuits[3]  # 555_timer_blinking_led
    print("render_circuit_answer for circuit 2:")
    print(render_circuit_answer(circuit_2))
else:
    print("No circuits available for circuit_2.")
