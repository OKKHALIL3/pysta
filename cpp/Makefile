CXX      ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra

sta_core: sta_core.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

# Solve the bundled example graph.
.PHONY: demo
demo: sta_core
	./sta_core ../examples/pipe.graph

# Regenerate the graph from the Python engine, then solve it in C++.
.PHONY: run
run: sta_core
	cd .. && python3 -m pysta export examples/pipe.v --lib examples/tiny.lib --sdc examples/pipe.sdc -o examples/pipe.graph
	./sta_core ../examples/pipe.graph

.PHONY: clean
clean:
	rm -f sta_core
