"""
tpu_driver.py
=============
Software "compiler" for the 8x8 Systolic Array Accelerator.

This single script replaces the old tpu_driver.py / tpu_driver2.py pair.
The previous tpu_driver.py only worked correctly for matrices that fit in
exactly one 8x8 tile (e.g. 8x8 * 8x8) -- it flattened the *whole* padded
matrix into the .hex files instead of slicing it into 8x8 tiles, so any
larger size (its own header comment suggested trying 10x10!) silently
produced wrong answers even in Exact mode. This version always tiles and
stitches properly (the logic tpu_driver2.py used), so any matrix size --
one tile or many -- is computed correctly. Set the dimensions below to
whatever you like, including non-multiples of 8 (e.g. 10x10, 5x7 * 7x11).
"""

import numpy as np
import subprocess
import os
import math
import shutil

# ==========================================
# 1. SYSTEM CONFIGURATION
# ==========================================
# Matrix dimensions. Any positive size works -- single 8x8 tile, a clean
# multiple of 8 (16x16, 24x24, ...), or a non-multiple that needs padding
# (10x10, 5x7, ...).
ROWS_A = 8
COLS_A = 8
ROWS_B = 8
COLS_B = 8

# Hardware Constraints
HW_TILE_SIZE = 8
MAX_INT8 = 127

# Operating Mode: 1 = Exact Engine (High Accuracy), 0 = Approximate Engine (Low Power)
HARDWARE_MODE = 1  # Change to 0 for Approximate Mode

# Paths relative to this script's location
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_DIR = os.path.join(ROOT_DIR, 'data')

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# ==========================================
# 2. INPUT VALIDATION
# ==========================================
if COLS_A != ROWS_B:
    raise ValueError(
        f"Non-conformable matrices for A @ B: A is {ROWS_A}x{COLS_A}, "
        f"B is {ROWS_B}x{COLS_B} (COLS_A must equal ROWS_B)."
    )
if min(ROWS_A, COLS_A, ROWS_B, COLS_B) <= 0:
    raise ValueError("Matrix dimensions must be positive integers.")
if HARDWARE_MODE not in (0, 1):
    raise ValueError("HARDWARE_MODE must be 0 (Approximate) or 1 (Exact).")

# ==========================================
# 3. DATA GENERATION & QUANTIZATION
# ==========================================
print("==================================================")
print("1. GENERATING AI DATA & QUANTIZING")
print("==================================================")

# Generate random floats between -1.0 and 1.0 (mimicking neural network weights)
float_A = np.random.uniform(-1.0, 1.0, (ROWS_A, COLS_A))
float_B = np.random.uniform(-1.0, 1.0, (ROWS_B, COLS_B))

# Find the absolute maximum value across both matrices for symmetric quantization
max_val = max(np.max(np.abs(float_A)), np.max(np.abs(float_B)))

# Guard against an all-zero input, which would otherwise divide by zero
if max_val == 0:
    print("Input matrices are all-zero; skipping quantization (scale factor = 1.0).")
    scale_factor = 1.0
else:
    # Calculate Scale Factor (S)
    scale_factor = max_val / MAX_INT8

print(f"Max Absolute Value: {max_val:.4f}")
print(f"Calculated Scale Factor: {scale_factor:.4f}")

# Quantize and round to nearest INT8, then clip defensively to the valid
# signed 8-bit range so a rounding edge case can never overflow the hex
# encoding below.
int8_A = np.clip(np.round(float_A / scale_factor), -128, 127).astype(int)
int8_B = np.clip(np.round(float_B / scale_factor), -128, 127).astype(int)

# ==========================================
# 4. ZERO-PADDING (Hardware Dimension Matching)
# ==========================================
# The hardware only natively processes 8x8 tiles. Pad every dimension up
# to the next multiple of 8 so it can be sliced cleanly into tiles.
pad_rows_A = math.ceil(ROWS_A / HW_TILE_SIZE) * HW_TILE_SIZE
pad_cols_A = math.ceil(COLS_A / HW_TILE_SIZE) * HW_TILE_SIZE
pad_rows_B = math.ceil(ROWS_B / HW_TILE_SIZE) * HW_TILE_SIZE
pad_cols_B = math.ceil(COLS_B / HW_TILE_SIZE) * HW_TILE_SIZE

padded_A = np.zeros((pad_rows_A, pad_cols_A), dtype=int)
padded_B = np.zeros((pad_rows_B, pad_cols_B), dtype=int)

padded_A[:ROWS_A, :COLS_A] = int8_A
padded_B[:ROWS_B, :COLS_B] = int8_B

# Calculate Golden Reference (Expected Answer) using the padded integer matrices
golden_output = np.dot(padded_A, padded_B)

# ==========================================
# 5. TILING & HEX CONVERSION
# ==========================================
def to_twos_complement_hex(val, bits=8):
    """Converts a negative or positive integer to a 2's complement hex string."""
    if val < 0:
        val = (1 << bits) + val
    return f"{val:0{bits // 4}X}"

print("\nSlicing Matrices into 8x8 Tiles & Writing Hex Files...")

num_tiles_row_A = pad_rows_A // HW_TILE_SIZE
num_tiles_col_A = pad_cols_A // HW_TILE_SIZE   # == num_tiles_row_B (inner/contraction dim)
num_tiles_col_B = pad_cols_B // HW_TILE_SIZE

tile_pairs = []

# Generate (A-tile, B-tile) pairs for Block Matrix Multiplication, ordered
# output-row, output-col, inner-k -- this order must match the stitching
# loop in Section 7 below.
for i in range(num_tiles_row_A):
    for j in range(num_tiles_col_B):
        for k in range(num_tiles_col_A):
            tile_A = padded_A[i * HW_TILE_SIZE:(i + 1) * HW_TILE_SIZE, k * HW_TILE_SIZE:(k + 1) * HW_TILE_SIZE]
            tile_B = padded_B[k * HW_TILE_SIZE:(k + 1) * HW_TILE_SIZE, j * HW_TILE_SIZE:(j + 1) * HW_TILE_SIZE]
            tile_pairs.append((tile_A, tile_B))

# Calculate total elements to process and log it
total_elements_sent = len(tile_pairs) * (HW_TILE_SIZE * HW_TILE_SIZE)

# Write Hex Files Sequentially per tile pairing
with open(os.path.join(DATA_DIR, 'matrix_a.hex'), 'w') as fa, \
     open(os.path.join(DATA_DIR, 'matrix_b.hex'), 'w') as fb:
    for tA, tB in tile_pairs:
        for val in tA.flatten():
            fa.write(to_twos_complement_hex(val, 8) + '\n')
        for val in tB.flatten():
            fb.write(to_twos_complement_hex(val, 8) + '\n')

# Write Golden Output (decimal, human-readable reference)
with open(os.path.join(DATA_DIR, 'expected_out.txt'), 'w') as f:
    for val in golden_output.flatten():
        f.write(str(val) + '\n')

# Write Config File (Line 1: Total Elements in A sent to hardware, Line 2: Mode)
with open(os.path.join(DATA_DIR, 'config.txt'), 'w') as f:
    f.write(str(total_elements_sent) + '\n')
    f.write(str(HARDWARE_MODE) + '\n')

print(f"-> Total elements sent to hardware: {total_elements_sent} ({len(tile_pairs)} tile(s))")
print(f"-> Hardware Mode Set To: {'EXACT (1)' if HARDWARE_MODE == 1 else 'APPROXIMATE (0)'}")

# ==========================================
# 6. AUTOMATED HARDWARE EXECUTION
# ==========================================
print("\n==================================================")
print("2. LAUNCHING HARDWARE SIMULATION")
print("==================================================")

if shutil.which("iverilog") is None or shutil.which("vvp") is None:
    raise RuntimeError(
        "iverilog/vvp not found on PATH. Install Icarus Verilog "
        "(e.g. `apt-get install iverilog`) before running this script."
    )

# Change working directory to ROOT so paths in Verilog work correctly
os.chdir(ROOT_DIR)

# 1. Compile the SystemVerilog files
compile_cmd = [
    "iverilog", "-g2012", "-o", "systolic_sim.vvp",
    "src/processing_element.sv",
    "src/systolic_array_8x8.sv",
    "tb/tb_systolic_array.sv"
]
print("Compiling SystemVerilog RTL...")
subprocess.run(compile_cmd, check=True)

# 2. Execute the simulation
run_cmd = ["vvp", "systolic_sim.vvp"]
print("Running Hardware Simulation...")
subprocess.run(run_cmd, check=True)

# ==========================================
# 7. VERIFICATION, STITCHING & RECOVERY
# ==========================================
print("\n==================================================")
print("3. VERIFICATION & ACCURACY CHECK")
print("==================================================")

# Read the hardware's integer output
hardware_results = []
with open(os.path.join(DATA_DIR, 'accumulator_output.txt'), 'r') as f:
    for line in f:
        line = line.strip()
        if line:
            hardware_results.append(int(line))

expected_count = total_elements_sent
if len(hardware_results) != expected_count:
    raise RuntimeError(
        f"Hardware produced {len(hardware_results)} result values, "
        f"expected {expected_count}. Check the testbench / data files."
    )

# Reconstruct and Stitch the Output matrix from the partial-sum tiles.
# Each hardware tile-run is independent (the testbench resets the
# accumulators between tiles), so partial products across the inner (k)
# dimension are summed here in software -- this loop order must match
# the tile_pairs generation order in Section 5.
hardware_matrix = np.zeros((pad_rows_A, pad_cols_B), dtype=int)
idx = 0

for i in range(num_tiles_row_A):
    for j in range(num_tiles_col_B):
        tile_sum = np.zeros((HW_TILE_SIZE, HW_TILE_SIZE), dtype=int)
        for k in range(num_tiles_col_A):
            chunk = hardware_results[idx: idx + (HW_TILE_SIZE * HW_TILE_SIZE)]
            idx += (HW_TILE_SIZE * HW_TILE_SIZE)
            tile_sum += np.array(chunk).reshape(HW_TILE_SIZE, HW_TILE_SIZE)
        hardware_matrix[i * HW_TILE_SIZE:(i + 1) * HW_TILE_SIZE, j * HW_TILE_SIZE:(j + 1) * HW_TILE_SIZE] = tile_sum

# Compare Hardware vs Golden Reference
differences = np.abs(hardware_matrix - golden_output)
error_count = np.sum(differences > 0)
total_calcs = golden_output.size

print(f"Total MAC Operations: {total_calcs}")
print(f"Errors Detected: {error_count}")

if error_count == 0:
    print("\n\u2705 TEST PASSED: Stitched hardware output perfectly matches the Golden Reference!")
else:
    print(f"\n\u26a0\ufe0f APPROXIMATION ACTIVE: {error_count} calculations deviated from exact math.")
    accuracy = ((total_calcs - error_count) / total_calcs) * 100
    print(f"Overall Mathematical Accuracy: {accuracy:.2f}%")

# De-quantize back to decimal floats for the user, and slice off the
# zero-padding so the printed result matches the requested ROWS_A x COLS_B.
final_decimal_matrix = hardware_matrix * (scale_factor * scale_factor)
final_decimal_matrix = final_decimal_matrix[:ROWS_A, :COLS_B]
print(f"\nFinal De-Quantized Matrix Output ({ROWS_A}x{COLS_B}, padding removed):")
print(final_decimal_matrix)
print("==================================================")
