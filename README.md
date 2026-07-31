# Systolic Array Accelerator

An 8x8 SystemVerilog systolic array for INT8 matrix multiplication with a
**dual-mode (Exact / Approximate) Processing Element**, driven end-to-end by
a Python "compiler" that quantizes, tiles, simulates, and verifies against a
golden reference — all with one command.

```
Python (quantize → tile → hex)  →  Icarus Verilog (simulate)  →  Python (stitch → verify)
```

## Why "approximate computing"?

Every Processing Element (PE) contains two multipliers:

- **Exact engine** — full-precision INT8 x INT8 multiply.
- **Approximate engine** — truncates the low 3 bits of each operand before
  multiplying (cheaper, lower-power logic), trading accuracy for power.

A single `mode` signal picks which product feeds the accumulator, so the same
hardware can run either "flavor" per batch:

| `mode` | Behavior | Use case |
|---|---|---|
| `1` | **Exact** — full-precision MAC | Accuracy-critical layers |
| `0` | **Approximate** — 3-LSB-truncated MAC | Error-resilient / power-constrained layers |

Because each output only accumulates 8 partial products (one 8x8 tile's inner
dimension), truncation error compounds fast — expect Approximate mode to
deviate from the golden reference on the large majority of outputs, not just
a "minor" fraction. Always check the printed accuracy number; don't assume
Approximate mode is "close enough" without measuring it for your data.

## Architecture

- **The grid:** 8x8 mesh of `processing_element` instances (64 PEs total),
  wired by `systolic_array_8x8`.
- **Data flow:** Matrix A streams in from the left, Matrix B streams in from
  the top, each PE passes its inputs one hop right / one hop down per cycle
  (diagonally staggered feed), and every PE accumulates `Σ(a·b)` in its own
  32-bit register.
- **Data width:** 8-bit signed (INT8) operands, 32-bit signed accumulators
  (plenty of headroom for 8 MACs of INT8 x INT8).
- **Tiling:** The hardware only natively understands one 8x8 tile at a time.
  Matrices of any size are zero-padded up to a multiple of 8, sliced into
  8x8 tiles, and — for matrices wider/taller than one tile — the partial
  products from each inner-dimension (`k`) tile are **summed back together
  in software** after simulation, since the testbench resets each PE's
  accumulator between hardware tile-runs.

## Directory structure

```
Systolic_Array_Accelerator/
├── src/
│   ├── processing_element.sv    # Dual-mode (Exact/Approx) INT8 MAC unit
│   └── systolic_array_8x8.sv    # Top-level module wiring 64 PEs together
├── tb/
│   └── tb_systolic_array.sv     # File I/O, memory loading, tile batching
├── software/
│   └── tpu_driver.py            # Quantize → tile → run sim → stitch → verify
├── docs/
│   └── ABOUT.txt                # Extended architecture write-up
└── data/                        # Generated at runtime — safe to .gitignore
    ├── config.txt                # element count + mode, read by the testbench
    ├── matrix_a.hex / matrix_b.hex   # tiled, two's-complement hex inputs
    ├── accumulator_output.txt    # raw, unstitched per-tile hardware output
    └── expected_out.txt          # golden reference (post-stitch comparison target)
```

## Requirements

- Python 3 with `numpy`
- [Icarus Verilog](http://iverilog.icarus.com/) (`iverilog`, `vvp`) on your `PATH`
  - Debian/Ubuntu: `apt-get install iverilog`
  - macOS: `brew install icarus-verilog`

## Usage

Everything is driven from one script — set your matrix sizes and mode at the
top of `software/tpu_driver.py`, then run it from the `software/` directory:

```bash
cd software
python3 tpu_driver.py
```

```python
ROWS_A = 8          # any positive size — single tile, a clean multiple of 8,
COLS_A = 8          # or a non-multiple like 10x10 that needs padding
ROWS_B = 8
COLS_B = 8

HARDWARE_MODE = 0   # 1 = Exact, 0 = Approximate
```

The script will:

1. Generate random float weights, quantize them to INT8, and zero-pad to a
   multiple of 8 in each dimension.
2. Slice into 8x8 tiles and write `matrix_a.hex` / `matrix_b.hex` / `config.txt`.
3. Compile and run the SystemVerilog simulation via Icarus Verilog.
4. Read back `accumulator_output.txt`, stitch multi-tile partial sums, and
   compare against the golden reference (`expected_out.txt`), printing the
   error count and overall accuracy.

You can also run the hardware side manually:

```bash
# from the project root, after data/*.hex and data/config.txt exist
iverilog -g2012 -o systolic_sim.vvp src/processing_element.sv src/systolic_array_8x8.sv tb/tb_systolic_array.sv
vvp systolic_sim.vvp
```

## `accumulator_output.txt` vs. `expected_out.txt`

These are **not** meant to be diffed line-for-line unless your matrix is
exactly one 8x8 tile. `accumulator_output.txt` is the raw, per-tile dump —
`(tile-pairs) x 64` lines, unsummed. `expected_out.txt` is the final,
already-summed golden matrix — `(padded rows) x (padded cols)` lines. For
anything with an inner dimension bigger than 8, multiple tile results must be
added together (which `tpu_driver.py` does before comparing) before they
correspond to a single golden value. Trust the script's printed
`Errors Detected` / accuracy line, not a manual diff of the two files.

## Verification status

Both single-tile (8x8) and multi-tile (e.g. 16x16, and non-square/non-
multiple-of-8 sizes like 5x7 x 7x11) configurations have been run in Exact
mode with **0 errors** against the golden reference. Approximate mode is
functionally correct but, as expected, deviates from the golden reference on
most outputs — check the printed accuracy for your specific data before
relying on it.

## License
