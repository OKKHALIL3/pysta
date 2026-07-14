# Constraints for pipe.v -- a 2 ns clock (500 MHz target).
create_clock -name clk -period 2.0 [get_ports clk]

# The outside world drives `a` and `b` a little after the clock edge,
# and needs `y` a little before the next one.
set_input_delay  0.2 -clock clk [get_ports a]
set_input_delay  0.2 -clock clk [get_ports b]
set_output_delay 0.3 -clock clk [get_ports y]
