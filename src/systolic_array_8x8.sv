module systolic_array_8x8 #(
    parameter DATA_WIDTH = 8,
    parameter ACC_WIDTH = 32
)(
    input  logic clk,
    input  logic rst_n,
    input logic mode,

    // Matrix inputs feeding the left edge and top edge
    input  logic signed [DATA_WIDTH-1:0] in_A_left [0:7],
    input  logic signed [DATA_WIDTH-1:0] in_B_top  [0:7],

    // 64 exposed accumulators 
    // NOTE: declared as `wire` (not `logic`) because Icarus Verilog does not
    // correctly propagate values through a whole-array port connection when
    // an unpacked multi-dimensional array output port is typed `logic`.
    // With `logic` here, out_accum reads back as X at the testbench even
    // though each PE's internal accum_out register holds the correct value.
    output wire signed [ACC_WIDTH-1:0] out_accum [0:7][0:7]
);
                                                                 
    // =======================================================
    // THE MESH NETWORK (Internal Silicon Traces)
    // =======================================================
    // We make the arrays size [0:8] to account for the incoming 
    // data at index 0, and the outgoing/terminated data at index 8.
    logic signed [DATA_WIDTH-1:0] horizontal_links [0:7][0:8]; 
    logic signed [DATA_WIDTH-1:0] vertical_links   [0:8][0:7];

    // Connect the physical input pins to the very first wires in the mesh
    genvar i;
    generate
        for (i = 0; i < 8; i = i + 1) begin : edge_connections
            assign horizontal_links[i][0] = in_A_left[i];
            assign vertical_links[0][i]   = in_B_top[i];
        end
    endgenerate

    // =======================================================
    // GENERATING THE 64 PROCESSING ELEMENTS
    // =======================================================
    genvar row, col;
    generate
        for (row = 0; row < 8; row = row + 1) begin : row_loop
            for (col = 0; col < 8; col = col + 1) begin : col_loop
                
                // Drop a PE at the current (row, col) intersection
                processing_element #(
                    .DATA_WIDTH(DATA_WIDTH), 
                    .ACC_WIDTH(ACC_WIDTH)
                ) PE_inst (
                    .clk(clk),
                    .rst_n(rst_n),
                    .mode(mode),
                    
                    // Inputs catch data from the previous column/row
                    .in_a(horizontal_links[row][col]),
                    .in_b(vertical_links[row][col]),
                    
                    // Outputs push data to the next column/row
                    .out_a(horizontal_links[row][col+1]),
                    .out_b(vertical_links[row+1][col]),
                    
                    // Expose the internal accumulator
                    .accum_out(out_accum[row][col])
                );

            end
        end
    endgenerate

endmodule
