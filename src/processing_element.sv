module processing_element #( 
    parameter DATA_WIDTH = 8, 
    parameter ACC_WIDTH = 32
) (
    input  logic clk,
    input  logic rst_n,
    input  logic mode,             // 1 = Exact Engine, 0 = Approximate Engine

    input  logic signed [DATA_WIDTH-1:0] in_a,
    input  logic signed [DATA_WIDTH-1:0] in_b,

    output logic signed [DATA_WIDTH-1:0] out_a,
    output logic signed [DATA_WIDTH-1:0] out_b,
    output logic signed [ACC_WIDTH-1:0] accum_out
);

    // Internal wires for the dual engines
    logic signed [15:0] exact_product;
    logic signed [15:0] approx_product;
    logic signed [15:0] final_product;

    // ENGINE A: The Heavy Exact Multiplier

    assign exact_product = in_a * in_b;

    // ENGINE B: The Lightweight Approximate Multiplier

    logic signed [DATA_WIDTH-1:0] a_chopped;
    logic signed [DATA_WIDTH-1:0] b_chopped;
    
    assign a_chopped = {in_a[7:3], 3'b000};
    assign b_chopped = {in_b[7:3], 3'b000};
    assign approx_product = a_chopped * b_chopped;

    // THE MULTIPLEXER (Logic Bypassing)

    assign final_product = (mode == 1'b1) ? exact_product : approx_product;

    // Standard MAC Pipeline
    always_ff @(posedge clk or negedge rst_n) begin
        if (rst_n == 1'b0) begin
            out_a     <= '0;
            out_b     <= '0;
            accum_out <= '0;
        end else begin
            out_a     <= in_a;
            out_b     <= in_b;
            accum_out <= accum_out + final_product;
        end
    end

endmodule
