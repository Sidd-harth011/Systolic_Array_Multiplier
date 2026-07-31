`timescale 1ns / 1ps

module tb_systolic_array_batch;

    // Parameters
    parameter DATA_WIDTH = 8;
    parameter ACC_WIDTH = 32;
    parameter ARRAY_DIM = 8;
    parameter TILE_ELEMENTS = 64;       // An 8x8 tile is 64 elements
    parameter MAX_MEM = 1048576;        // 1 Megabyte array (Supports up to 1024x1024 matrices)

    // Clock and Reset
    logic clk;
    logic rst_n;
    logic mode; // 1 = Exact Engine, 0 = Approximate Engine

    // Hardware Inputs & Outputs
    logic signed [DATA_WIDTH-1:0] in_A_left [0:ARRAY_DIM-1];
    logic signed [DATA_WIDTH-1:0] in_B_top  [0:ARRAY_DIM-1];
    wire  signed [ACC_WIDTH-1:0]  out_accum [0:ARRAY_DIM-1][0:ARRAY_DIM-1];

    // Giant Virtual Memory Arrays
    logic [DATA_WIDTH-1:0] memory_A [0:MAX_MEM-1];
    logic [DATA_WIDTH-1:0] memory_B [0:MAX_MEM-1];

    // Loop Tracking Variables
    integer total_elements_A;
    integer total_tiles;
    integer current_tile;
    integer file_out;
    integer config_file;
    integer hardware_mode_int; // NEW: Added to safely read the integer from the text file
    integer i, j, clk_cycle;

    // 1. Instantiate the 8x8 Hardware
    systolic_array_8x8 #(
        .DATA_WIDTH(DATA_WIDTH),
        .ACC_WIDTH(ACC_WIDTH)
    ) uut (
        .clk(clk),
        .rst_n(rst_n),
        .mode(mode),           // NEW: The dynamic mode signal is now wired to the hardware
        .in_A_left(in_A_left),
        .in_B_top(in_B_top),
        .out_accum(out_accum)
    );

    // 2. Generate the Clock (100 MHz)
    always #5 clk = ~clk;

    // 3. The Main Batch-Processing Control Block
    initial begin
        // Initialize Control Signals
        clk = 0;
        rst_n = 0;
        mode = 1; // Default to Exact just in case
        current_tile = 0;
        
        for (i = 0; i < ARRAY_DIM; i++) begin
            in_A_left[i] = '0;
            in_B_top[i]  = '0;
        end

        // Open the output file for hardware answers
        file_out = $fopen("data/accumulator_output.txt", "w");
        if (file_out == 0) begin
            $display("FATAL ERROR: Could not open data/accumulator_output.txt for writing");
            $finish;
        end

        // Read the exact number of elements and the hardware mode from Python's config file
        config_file = $fopen("data/config.txt", "r");
        if (config_file == 0) begin
            $display("FATAL ERROR: Could not open config.txt");
            $finish;
        end
        
        // Read Line 1: Total Elements
        $fscanf(config_file, "%d", total_elements_A);
        
        // Read Line 2: Hardware Mode (1 or 0)
        $fscanf(config_file, "%d", hardware_mode_int);
        
        $fclose(config_file);

        // Assign the read integer to the 1-bit logic signal
        mode = hardware_mode_int[0];

        // Load the massive pre-packed data from Python
        $readmemh("data/matrix_a.hex", memory_A);
        $readmemh("data/matrix_b.hex", memory_B);

        total_tiles = total_elements_A / TILE_ELEMENTS;

        $display("==================================================");
        $display("STARTING BATCH PROCESSING");
        $display("Total Elements to Process: %0d", total_elements_A);
        $display("Total 8x8 Tiles Detected: %0d", total_tiles);
        $display("Hardware Mode Selected: %0s", (mode == 1'b1) ? "EXACT (High Precision)" : "APPROXIMATE (Power Saving)");
        $display("==================================================");

        // Reset the hardware
        #20 rst_n = 1;

        // =======================================================
        // THE CONTINUOUS TILING LOOP
        // =======================================================
        while (current_tile < total_tiles) begin
            $display("-> Feeding Tile %0d into hardware...", current_tile + 1);

            // Defensively clear the edge inputs before this tile's feed
            // begins, so no stale value driven at the end of the previous
            // tile's staggering loop can linger into the reset window.
            for (i = 0; i < ARRAY_DIM; i++) begin
                in_A_left[i] = '0;
                in_B_top[i]  = '0;
            end

            // The Staggering Loop: Feeds the 64 elements with diagonal skew
            for (clk_cycle = 0; clk_cycle < (ARRAY_DIM * 2); clk_cycle++) begin
                @(posedge clk);
                
                for (i = 0; i < ARRAY_DIM; i++) begin
                    // Matrix A Feeder (Rows entering from the Left)
                    if (clk_cycle >= i && clk_cycle < i + ARRAY_DIM) begin
                        in_A_left[i] <= memory_A[current_tile * TILE_ELEMENTS + (i * ARRAY_DIM) + (clk_cycle - i)];
                    end else begin
                        in_A_left[i] <= '0; // Push zero bubbles when idle
                    end

                    // Matrix B Feeder (Columns entering from the Top)
                    if (clk_cycle >= i && clk_cycle < i + ARRAY_DIM) begin
                        in_B_top[i] <= memory_B[current_tile * TILE_ELEMENTS + ((clk_cycle - i) * ARRAY_DIM) + i];
                    end else begin
                        in_B_top[i] <= '0; // Push zero bubbles when idle
                    end
                end
            end

            // Wait for the pipeline to finish crunching this specific tile
            repeat (ARRAY_DIM * 3) @(posedge clk);

            // Write the 64 answers of this tile to the output file
            for (i = 0; i < ARRAY_DIM; i++) begin
                for (j = 0; j < ARRAY_DIM; j++) begin
                    $fdisplay(file_out, "%0d", out_accum[i][j]);
                end
            end
            
            $display("-> Tile %0d complete. Answers appended.", current_tile + 1);

            // Move to the next 64 elements
            current_tile++;
            
            // Pulse reset to clear the accumulators for the next independent tile
            rst_n = 0;
            #10 rst_n = 1;
        end

        // Cleanup
        $display("==================================================");
        $display("BATCH PROCESSING COMPLETE.");
        $display("All tiles processed. Python can now wake up and stitch the matrix!");
        $fclose(file_out);
        $finish;
    end

endmodule
