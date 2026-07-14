// A tiny gate-level pipeline, the kind of netlist synthesis produces.
//
//   a --[DFF r0]-- q0 --\
//                        NAND2 g0 -- n0 --[INV g1]-- d1 --[DFF r1]-- q1 --[BUF g2]-- y
//   b ------------------/
//
// It exercises all three path types STA cares about:
//   * input-to-register :  a  -> r0/D
//   * register-to-register: r0/Q -> g0 -> g1 -> r1/D   (usually the critical one)
//   * register-to-output :  r1/Q -> g2 -> y
module pipe (clk, a, b, y);
  input  clk, a, b;
  output y;
  wire   q0, n0, d1, q1;

  DFF   r0 (.CK(clk), .D(a),  .Q(q0));
  NAND2 g0 (.A(q0),   .B(b),  .Y(n0));
  INV   g1 (.A(n0),   .Y(d1));
  DFF   r1 (.CK(clk), .D(d1), .Q(q1));
  BUF   g2 (.A(q1),   .Y(y));
endmodule
