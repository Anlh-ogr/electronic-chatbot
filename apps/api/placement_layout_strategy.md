# Placement Layout Strategy for BJT and Op-Amp Amplifier Schematics

---

## 1. Objective

This document describes the schematic placement strategy for an analog amplifier design system focused on BJT NPN topologies (common-emitter, common-base, common-collector) and op-amp topologies (inverting, non-inverting, differential).

The goal of placement is to produce a readable schematic that follows the signal flow from `CIN/IN` to `COUT/OUT` while clearly expressing the power axis from `VCC` down to `GND/0`.

Placement must work for both single-stage circuits and multi-stage circuits of 2 to 3 stages, including:

- BJT multistage
- Op-amp multistage
- BJT-OpAmp mixed multistage
- BJT 2-stage with direct coupling (DC coupling)
- BJT 2-stage with capacitor coupling (AC coupling)

---

## 2. Layout Foundation

PyGraphviz uses the Graphviz `dot` engine to produce hierarchical layouts for directed graphs, which serves as the basis for inferring schematic component placement according to signal flow instead of applying force-based relaxation.

With `rankdir=LR`, nodes of higher rank are placed progressively to the right, fitting the flow `input -> active stage -> output`. With `rankdir=TB`, nodes are prioritized top-to-bottom, fitting the power axis anchored to ground.

The KiCad `.kicad_sch` file is a readable text/s-expression format. The placement engine only needs to produce valid coordinates, rotation angles, and connections in order to compile a correct schematic.

### 2.1 Global Constants

All placement calculations use the following shared constants. These values must be imported at the top of every placement module.

```python
# placement_constants.py

GRID_MM: float = 2.54                    # KiCad standard grid (100 mil)
SHEET_CENTER: tuple = (150.0, 100.0)     # mm - center of the A4 schematic sheet
PIN_PITCH_MM: float = 2.54              # standard pin-to-pin distance in KiCad symbols

INTER_STAGE_GAP_AC: int = 5             # grid units between stages when AC-coupled
INTER_STAGE_GAP_DC: int = 3             # grid units between stages when DC-coupled

def grid(units: int) -> float:
    return units * GRID_MM
```

### 2.2 Symbol Bounding Boxes

Each symbol occupies a rectangular bounding box used for overlap detection. Values are in grid units (multiply by `GRID_MM` to get mm).

```python
SYMBOL_BBOX_GRID: dict[str, tuple[int, int]] = {
    # (width, height) in grid units
    "bjt_npn":      (2, 3),
    "bjt_pnp":      (2, 3),
    "opamp_ic":     (4, 4),
    "resistor":     (1, 2),
    "capacitor":    (1, 2),
    "power_supply": (1, 1),
    "ground":       (1, 1),
    "connector":    (1, 1),
}
```

### 2.3 PyGraphviz Position Conversion

Graphviz `dot` returns node positions as a string `"x,y"` in **points** (1 point = 1/72 inch). These must be converted to millimetres before use in KiCad placement.

```python
GRAPHVIZ_POINTS_TO_MM: float = 25.4 / 72.0   # 1 point = 0.3528 mm

def parse_graphviz_pos(pos_str: str) -> tuple[float, float]:
    x_pt, y_pt = (float(v) for v in pos_str.split(","))
    return x_pt * GRAPHVIZ_POINTS_TO_MM, y_pt * GRAPHVIZ_POINTS_TO_MM
```

---

## 3. General Principles

### 3.1 Layout Center

The active device must occupy the center zone of each block:

- BJT: the transistor of the stage sits at the center.
- Op-amp: the op-amp IC of the stage sits at the center.
- For multistage circuits, each stage has its own center block, and all stages are arranged left to right.

The center of the full schematic is fixed at `SHEET_CENTER = (150.0, 100.0) mm`. For a single-stage circuit the active device is placed exactly at `SHEET_CENTER`. For multistage circuits, stage centers are distributed symmetrically around `SHEET_CENTER` along the X axis.

### 3.2 Rotation Convention

KiCad standard library symbols for passive components are defined in a **vertical default orientation**: Pin 1 at the top, Pin 2 at the bottom. This is the library origin state, not a horizontal one.

Rotation angles follow KiCad convention:

- `0`: component retains its **default vertical orientation** - Pin 1 top, Pin 2 bottom. Used for components on the vertical power axis.
- `90`: component is rotated to a **horizontal orientation** - Pin 1 left, Pin 2 right. Used for components on the horizontal signal path.

#### Role-to-Rotation Table

| Role            | Component examples      | Required orientation                               | Correct rotation |
|-----------------|-------------------------|----------------------------------------------------|-----------------|
| load            | RC, RD                  | Vertical - on the supply-to-collector axis         | 0               |
| degeneration    | RE, RE1, RE2, RS        | Vertical - on the emitter/source-to-GND axis       | 0               |
| bias_top        | R1 (upper divider)      | Vertical - on the VCC-to-base axis                 | 0               |
| bias_bottom     | R2 (lower divider)      | Vertical - on the base-to-GND axis                 | 0               |
| bypass_cap      | CE                      | Vertical - parallel to the emitter resistor branch | 0               |
| supply          | VCC                     | Vertical power symbol                              | 0               |
| ground          | GND                     | Vertical ground symbol                             | 0               |
| coupling_in     | CIN, C1                 | Horizontal - on the signal input path              | 90              |
| coupling_out    | COUT, C2                | Horizontal - on the signal output path             | 90              |
| feedback        | Rf, Rg                  | Horizontal - feedback loop runs left-right         | 90              |
| unknown_passive | Any unclassified R or C | Vertical by default                                | 0               |

BJT and op-amp symbols follow their own library orientation independently of this rule. Their rotation is determined by the requirement that the input pin faces left and the output pin faces right within the block.

#### Role-to-Rotation Reference (code)

```python
ROLE_ROTATION: dict[str, int] = {
    "bias_top":        0,
    "bias_bottom":     0,
    "load":            0,
    "degeneration":    0,
    "bypass_cap":      0,
    "supply":          0,
    "ground":          0,
    "unknown_passive": 0,
    "coupling_in":     90,
    "coupling_out":    90,
    "feedback":        90,
}
```

#### Pin Offset Rotation

All pin offset calculations must apply a rotation transform when `rotation != 0`.

```python
import math

def rotate_offset(dx: float, dy: float, rotation_deg: int) -> tuple[float, float]:
    rad = math.radians(rotation_deg)
    cos_r = round(math.cos(rad))
    sin_r = round(math.sin(rad))
    return (
        dx * cos_r - dy * sin_r,
        dx * sin_r + dy * cos_r,
    )

# Standard KiCad passive pin offsets at 0 (library default):
#   Pin 1: (0, -2.54)  - top
#   Pin 2: (0, +2.54)  - bottom
#
# After 90 rotation:
#   Pin 1: (-2.54, 0)  - left
#   Pin 2: (+2.54, 0)  - right
```

**Critical**: Wire endpoints must always use the resolved post-rotation pin coordinates. Using raw library offsets for rotated components produces disconnected wires in `.kicad_sch`.

### 3.3 Placement Density

Components must not be placed too far apart. The block must be concentrated in the center region of the schematic canvas rather than spread across the full sheet.

Spacing must be sufficient to avoid symbol overlap, avoid label collision, and prevent wires from crossing through the body of a component.

### 3.4 Two Readable Flows

The schematic must clearly express both flows simultaneously:

- **Power flow**: `VCC -> load/bias -> active device -> degeneration -> GND`
- **Signal flow**: `CIN/IN -> input node -> active device -> output node -> COUT/OUT`

---

## 4. Placement Architecture

### 4.1 Block Model

Each stage is represented as a block composed of five zones:

| Zone        | Role                                        | Preferred Direction                          |
|-------------|---------------------------------------------|----------------------------------------------|
| Input zone  | CIN, input resistor, source/input connector | Horizontal                                   |
| Bias zone   | Voltage divider, feedback input, bias R     | Vertical                                     |
| Center zone | Q1 or U1                                    | Center anchor                                |
| Load zone   | RC or feedback/output load                  | Vertical or Horizontal depending on topology |
| Output zone | COUT, output connector, next-stage coupling | Horizontal                                   |

### 4.2 Anchor Offsets per Topology

All offsets are in **grid units** relative to the active device center. Multiply by `GRID_MM` to get millimetres. Positive X = right, positive Y = down (KiCad Y-axis convention).

#### BJT Common-Emitter

```python
CE_OFFSETS: dict[str, tuple[int, int]] = {
    "VCC":  ( 0, -5),   # above RC
    "RC":   ( 0, -3),   # above Q1 on collector branch
    "Q1":   ( 0,  0),   # center anchor
    "R1":   (-3, -2),   # upper bias divider, left side
    "R2":   (-3, +2),   # lower bias divider, left side
    "RE1":  ( 0, +3),   # emitter degeneration (upper)
    "RE2":  ( 0, +5),   # emitter degeneration (lower, bypassed)
    "CE":   (+2, +5),   # bypass cap beside RE2
    "CIN":  (-5,  0),   # input coupling, left
    "COUT": (+5,  0),   # output coupling, right
    "GND":  ( 0, +7),   # ground below RE
}
```

#### BJT Common-Base

```python
CB_OFFSETS: dict[str, tuple[int, int]] = {
    "VCC":  ( 0, -5),
    "RC":   ( 0, -3),   # collector load above Q1
    "Q1":   ( 0,  0),   # center anchor
    "R1":   (-3, -1),   # base bias upper (local, not in signal path)
    "R2":   (-3, +1),   # base bias lower
    "CB":   (-3,  0),   # base bypass cap (if present)
    "RE":   ( 0, +3),   # emitter / input resistor
    "CIN":  (-5, +3),   # input enters emitter side
    "COUT": (+5,  0),   # output at collector
    "GND":  ( 0, +5),
}
```

#### BJT Common-Collector

```python
CC_OFFSETS: dict[str, tuple[int, int]] = {
    "VCC":  ( 0, -3),   # collector connected directly to supply
    "Q1":   ( 0,  0),   # center anchor
    "R1":   (-3, -2),   # base bias upper
    "R2":   (-3, +2),   # base bias lower
    "RE":   ( 0, +3),   # emitter resistor to GND
    "CIN":  (-5,  0),   # input at base
    "COUT": (+5, +3),   # output at emitter
    "GND":  ( 0, +5),
}
```

#### Op-Amp Inverting

```python
INV_OFFSETS: dict[str, tuple[int, int]] = {
    "VCC":  ( 0, -4),   # VS+ supply above
    "VEE":  ( 0, +4),   # VS- supply below
    "CPS":  ( 0, -3),   # decoupling cap VS+ to 0
    "CPN":  ( 0, +3),   # decoupling cap VS- to 0
    "U1":   ( 0,  0),   # center anchor
    "Rin":  (-4,  0),   # input resistor into - pin
    "Rf":   ( 0, -2),   # feedback resistor (horizontal, above U1)
    "Rgnd": (-3, +2),   # + pin to GND reference
    "CIN":  (-6,  0),   # input coupling
    "COUT": (+4,  0),   # output coupling
    "GND":  ( 0, +5),
}
```

#### Op-Amp Non-Inverting

```python
NONINV_OFFSETS: dict[str, tuple[int, int]] = {
    "VCC":  ( 0, -4),
    "VEE":  ( 0, +4),
    "CPS":  ( 0, -3),
    "CPN":  ( 0, +3),
    "U1":   ( 0,  0),
    "CIN":  (-6,  0),   # input at + pin
    "Rf":   (+2, +2),   # feedback from OUT to - pin
    "Rg":   ( 0, +2),   # - pin to GND
    "COUT": (+5,  0),
    "GND":  ( 0, +5),
}
```

#### Op-Amp Differential

```python
DIFF_OFFSETS: dict[str, tuple[int, int]] = {
    "VCC":  ( 0, -4),
    "VEE":  ( 0, +4),
    "CPS":  ( 0, -3),
    "CPN":  ( 0, +3),
    "U1":   ( 0,  0),
    "Rin1": (-4, -1),   # input resistor into + pin
    "Rin2": (-4, +1),   # input resistor into - pin
    "Rf1":  (+2, -1),   # feedback / gain resistor upper
    "Rf2":  (+2, +1),   # feedback / gain resistor lower
    "CIN1": (-6, -1),
    "CIN2": (-6, +1),
    "COUT": (+5,  0),
    "GND":  ( 0, +5),
}
```

### 4.3 From Graph to Coordinates

The placement graph should be structured as follows:

- The center node is the active device.
- Input nodes connect from the left.
- Power nodes connect from above downward.
- Ground nodes are anchored at the bottom.
- Output nodes connect to the right.

PyGraphviz `dot` supports `rank=same` to hold a set of nodes on the same horizontal level when needed.

### 4.4 Proposed Pipeline

1. Classify topology family.
2. Infer component roles from the netlist.
3. Build a directed placement graph using PyGraphviz.
4. Run `layout(prog="dot")` to obtain node positions.
5. Convert Graphviz point coordinates to mm using `parse_graphviz_pos()`.
6. Apply anchor offsets per topology (section 4.2) centered on `SHEET_CENTER`.
7. Apply rotation rules per role (section 3.2).
8. Run post-processing: snap to grid, resolve overlaps using `SYMBOL_BBOX_GRID`, reroute wires, validate pin-net consistency.
9. Serialize to `.kicad_sch`.

---

## 5. Topology-Specific Layouts

### 5.1 BJT Common-Emitter

- `Q1` at the center (`SHEET_CENTER`).
- `RC` at offset `(0, -3)` grid units above `Q1` on the collector branch.
- `RE1` / `RE2` at offsets `(0, +3)` and `(0, +5)` below `Q1` running to `GND`.
- `R1` / `R2` at offsets `(-3, -2)` and `(-3, +2)` to the left, forming the base bias divider.
- `CIN` at offset `(-5, 0)` horizontal from the left into the base node.
- `COUT` at offset `(+5, 0)` horizontal from the collector node to the right.
- `CE` at offset `(+2, +5)` parallel to `RE2`, bypassing the lower emitter resistor only.

Readable axes - Vertical: `VCC -> RC -> Q1 -> RE1 -> RE2 -> GND`. Horizontal: `CIN -> base -> collector -> COUT`.

### 5.2 BJT Common-Base

- `Q1` at the center.
- Base bias `R1` / `R2` anchored locally at `(-3, -1)` and `(-3, +1)` - not in the signal path.
- Input enters the emitter side: `CIN` at offset `(-5, +3)` lower-left.
- Output taken at collector: `COUT` at offset `(+5, 0)`.
- `RC` at `(0, -3)` above; `RE` at `(0, +3)` below.
- The input does not enter the base. The input path routes into the emitter zone.

### 5.3 BJT Common-Collector

- `Q1` at the center.
- Collector connects directly to supply at offset `(0, -3)` - no load resistor on the collector branch.
- Base bias `R1` / `R2` at `(-3, -2)` and `(-3, +2)`.
- `RE` at `(0, +3)` going to `GND`.
- `CIN` at `(-5, 0)` into the base; `COUT` at `(+5, +3)` taken from the emitter.

### 5.4 Op-Amp Inverting

- `U1` at the center.
- `Rin` at `(-4, 0)` entering the `-` pin from the left.
- `Rf` at `(0, -2)` running horizontally above `U1` from output back to `-` pin.
- `+` pin tied to GND via `Rgnd` at `(-3, +2)`.
- `COUT` at `(+4, 0)` to the right.
- Decoupling caps at `(0, -3)` and `(0, +3)` close to VS+ and VS-.

### 5.5 Op-Amp Non-Inverting

- `U1` at the center.
- `CIN` at `(-6, 0)` entering the `+` pin.
- Feedback network `Rf` / `Rg` at offsets `(+2, +2)` and `(0, +2)` at lower-right.
- `COUT` at `(+5, 0)`.

### 5.6 Op-Amp Differential

- `U1` at the center.
- Two input resistors `Rin1` / `Rin2` at `(-4, -1)` and `(-4, +1)` symmetrically on the left.
- Feedback / gain resistors `Rf1` / `Rf2` at `(+2, -1)` and `(+2, +1)` symmetrically.
- `COUT` at `(+5, 0)`.

---

## 6. Multi-Stage Layout

### 6.1 General Rules

Multi-stage circuits of 2 to 3 stages are organized as stage blocks arranged along the left-to-right axis. Each stage preserves its own internal placement rules: active device at center, power above, ground below, input from left, output to right.

Stage centers are computed as:

```python
def stage_centers(
    n_stages: int,
    sheet_center: tuple[float, float] = SHEET_CENTER,
    stage_width_grid: int = 12,
) -> list[tuple[float, float]]:
    cx, cy = sheet_center
    total_width = (n_stages - 1) * stage_width_grid * GRID_MM
    x_start = cx - total_width / 2
    return [
        (x_start + i * stage_width_grid * GRID_MM, cy)
        for i in range(n_stages)
    ]
```

### 6.2 BJT Multistage

Two or three BJT stages in a horizontal chain `Stage1 -> Stage2 -> Stage3`. The bias network of each stage is kept local.

**AC coupling**: inter-stage coupling capacitor placed in the channel at gap `INTER_STAGE_GAP_AC` (5 grid units) between blocks. The capacitor role is `coupling_in` for the receiving stage and `coupling_out` for the driving stage.

**DC coupling**: the output node of the preceding stage connects directly to the input/bias node of the following stage at gap `INTER_STAGE_GAP_DC` (3 grid units). No capacitor is placed in the channel.

### 6.3 Op-Amp Multistage

Op-amp stages arranged left to right. Each stage must preserve sufficient local spacing so the feedback loop does not visually intrude into the adjacent stage zone. Use `INTER_STAGE_GAP_AC` as the minimum channel width between op-amp stages regardless of coupling type.

### 6.4 BJT-OpAmp Mixed Multistage

BJT stage at the front; op-amp stage following. Each family preserves its own offset table (section 4.2). Bridge components between stages are placed at the midpoint of the inter-stage channel and not inside the center zone of either block.

---

## 7. Role of PyGraphviz

PyGraphviz is best suited for generating a **fast macro layout based on a directed graph**, especially when the stage count varies or when the number of resistors and capacitors changes.

`dot` is the appropriate engine for directed graphs with hierarchical layering. It differs from `neato` (spring model) and `fdp` (force-directed), both of which produce non-deterministic layouts unsuitable for schematic placement.

### Example Graph Construction (BJT CE)

```python
import pygraphviz as pgv
from placement_constants import parse_graphviz_pos, SHEET_CENTER, CE_OFFSETS, GRID_MM

G = pgv.AGraph(directed=True)
G.graph_attr["rankdir"] = "LR"

# Signal flow
G.add_edge("IN",   "CIN")
G.add_edge("CIN",  "Q1")
G.add_edge("Q1",   "COUT")
G.add_edge("COUT", "OUT")

# Power flow
G.add_edge("VCC", "RC")
G.add_edge("RC",  "Q1")
G.add_edge("Q1",  "RE1")
G.add_edge("RE1", "RE2")
G.add_edge("RE2", "GND")

# Bias
G.add_edge("VCC", "R1")
G.add_edge("R1",  "Q1")
G.add_edge("Q1",  "R2")
G.add_edge("R2",  "GND")

# Bypass
G.add_edge("RE2", "CE")
G.add_edge("CE",  "GND")

G.layout(prog="dot")

# Step 1: get graph positions for unknown extras
graph_positions = {}
for node in G.nodes():
    pos_str = node.attr.get("pos", "0,0")
    graph_positions[str(node)] = parse_graphviz_pos(pos_str)

# Step 2: override with topology anchor offsets centered on SHEET_CENTER
cx, cy = SHEET_CENTER
placements = {}
for comp_id, (gx, gy) in graph_positions.items():
    key = comp_id.upper()
    if key in CE_OFFSETS:
        dx, dy = CE_OFFSETS[key]
        placements[comp_id] = (cx + dx * GRID_MM, cy + dy * GRID_MM)
    else:
        placements[comp_id] = (cx + gx, cy + gy)
```

---

## 8. Placement Template Mapping

Rotation values follow KiCad convention: `0` = vertical default; `90` = horizontal.

| Topology      | Center | Input Side                              | Output Side                 | Power Axis              | Ground Axis                            | Unique Characteristic                               |
|---------------|--------|-----------------------------------------|-----------------------------|-------------------------|----------------------------------------|-----------------------------------------------------|
| CE            | Q1     | Base from left; CIN rot=90, off=(-5,0)  | COUT rot=90, off=(+5,0)     | RC rot=0, off=(0,-3)    | RE/RE1/RE2 rot=0; CE rot=0 off=(+2,+5) | CE bypasses RE2 only; split-emitter when gain given |
| CB            | Q1     | Emitter lower-left; CIN rot=90, off=(-5,+3) | COUT rot=90, off=(+5,0) | RC rot=0, off=(0,-3)    | RE rot=0, off=(0,+3)                   | Base bias local; input enters emitter not base      |
| CC            | Q1     | Base from left; CIN rot=90, off=(-5,0)  | Emitter; COUT rot=90, off=(+5,+3) | Collector to supply, no RC | RE rot=0, off=(0,+3)              | Output at emitter; emitter-follower                 |
| Inverting     | U1     | Rin rot=90, off=(-4,0) into -           | COUT rot=90, off=(+4,0)     | VS+ rot=0, off=(0,-4)   | VS- rot=0, off=(0,+4); C decoup rot=0  | Rf rot=90 off=(0,-2), loops OUT to - pin            |
| Non-Inverting | U1     | CIN rot=90, off=(-6,0) into +           | COUT rot=90, off=(+5,0)     | VS+ rot=0, off=(0,-4)   | VS- rot=0, off=(0,+4); C decoup rot=0  | Rf/Rg at lower-right off=(+2,+2) and (0,+2)        |
| Differential  | U1     | Rin1/Rin2 rot=90, off=(-4,-1),(-4,+1)  | COUT rot=90, off=(+5,0)     | VS+ rot=0, off=(0,-4)   | VS- rot=0, off=(0,+4); C decoup rot=0  | Symmetric dual-input; Rf1/Rf2 at (+2,-1),(+2,+1)   |

---

## 9. Implementation Rules

- Use PyGraphviz to lay out macro nodes by stage graph.
- Convert Graphviz positions to mm using `parse_graphviz_pos()`.
- Override converted positions with the topology-specific anchor offsets from section 4.2, centered on the active device at `SHEET_CENTER` (or its stage-specific center from `stage_centers()`).
- Allow only rotation values `0` or `90` from `ROLE_ROTATION`.
- Extra R/C components with role `unknown_passive` are placed in the bias zone at rotation `0`, offset `(+3, col * 2)` from the active device center where `col` increments per component.
- All power symbols above; all ground symbols below.
- Inter-stage bridge components placed at midpoint of the inter-stage channel, not inside any stage block.
- Compact the full block toward `SHEET_CENTER`.

The existing exporter provides snap-to-grid, resolve-component-overlaps (using `SYMBOL_BBOX_GRID`), fit-to-sheet, reroute wires, and validate pin-net consistency. PyGraphviz placement feeds into these passes as the initial coordinate set.

---

## 10. Quality Criteria

A schematic layout is considered acceptable when all six criteria are satisfied:

1. The signal direction left to right is readable.
2. The power direction top to bottom is readable.
3. The active device of each stage occupies the center of its block.
4. No symbol overlap (verified using `SYMBOL_BBOX_GRID`) and no wire crossing through a symbol body.
5. Component spacing is tight enough that the circuit is concentrated at `SHEET_CENTER`.
6. The layout holds for variable numbers of resistors and capacitors without breaking the block structure.

---

## 11. Implementation Steps

- **Step 1**: Define `placement_constants.py` containing `GRID_MM`, `SHEET_CENTER`, `SYMBOL_BBOX_GRID`, `INTER_STAGE_GAP_AC`, `INTER_STAGE_GAP_DC`, `parse_graphviz_pos`, `rotate_offset`.
- **Step 2**: Classify topology family and build `ROLE_ROTATION` mapping per component.
- **Step 3**: Select the matching offset table from section 4.2 (`CE_OFFSETS`, `CB_OFFSETS`, `CC_OFFSETS`, `INV_OFFSETS`, `NONINV_OFFSETS`, `DIFF_OFFSETS`).
- **Step 4**: For multistage, compute stage centers with `stage_centers(n)` and apply the per-stage offset table relative to each stage center.
- **Step 5**: Build the PyGraphviz directed graph and run `layout(prog="dot")`.
- **Step 6**: Override graph positions with anchor-offset-table coordinates for recognized components; use graph positions only for unrecognized extras.
- **Step 7**: Apply `ROLE_ROTATION` and compute resolved pin positions with `rotate_offset()`.
- **Step 8**: Run the existing post-processing passes: snap, overlap resolution, reroute, pin-net validation.
- **Step 9**: Serialize to `.kicad_sch`.

KiCad schematic is a text/s-expression format. Produce valid placement and wiring first, then serialize - do not patch the final text output directly.
