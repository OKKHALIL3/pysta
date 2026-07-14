// Deterministic sequential design used with unit.lib.
//   a --[DFF r0]-- q0 --\
//                        AND2 g0 -- d1 --[INV g1]-- d2 --[DFF r1]-- y
//   b ------------------/
// Hand-computed reg-to-reg arrival: 0.30 (CK->Q) + 0.25 (AND2) + 0.10 (INV) = 0.65.
module m (clk, a, b, y);
  input  clk, a, b;
  output y;
  wire   q0, d1, d2;

  DFF  r0 (.CK(clk), .D(a),  .Q(q0));
  AND2 g0 (.A(q0),   .B(b),  .Y(d1));
  INV  g1 (.A(d1),   .Y(d2));
  DFF  r1 (.CK(clk), .D(d2), .Q(y));
endmodule
