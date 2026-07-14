// PySTA C++ core -- the performance-critical timing-graph solver.
//
// This is the hot path of static timing analysis. On a real design the timing
// graph has millions of nodes, and the longest-path propagation over it
// dominates runtime -- so it's the natural piece to implement in C++.
//
// It reads a "resolved timing graph": each node's launch arrival (for path
// starts), each edge's already-computed delay, and each endpoint's required
// time. It then runs the same algorithm as pysta/timing.py -- forward arrival,
// backward required, slack, worst negative slack, and the critical path -- and
// the two implementations are cross-checked in tests/test_cpp_core.py.
//
// Input format (whitespace-separated; produced by `python -m pysta export`):
//     nodes N
//     <idx> <name> <start 0|1> <launch>     x N
//     edges M
//     <src> <dst> <delay>                   x M
//     endpoints K
//     <idx> <required>                      x K

#include <algorithm>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

struct Edge {
    int src, dst;
    double delay;
};

struct Graph {
    std::vector<std::string> name;
    std::vector<char> is_start;
    std::vector<double> launch;
    std::vector<Edge> edges;
    std::vector<int> ep_node;
    std::vector<double> ep_required;
};

bool read_graph(std::istream& in, Graph& g) {
    std::string tok;
    int n = 0;
    if (!(in >> tok >> n) || tok != "nodes" || n < 0) return false;
    g.name.assign(n, "");
    g.is_start.assign(n, 0);
    g.launch.assign(n, 0.0);
    for (int k = 0; k < n; ++k) {
        int idx, start;
        std::string nm;
        double launch;
        if (!(in >> idx >> nm >> start >> launch) || idx < 0 || idx >= n) return false;
        g.name[idx] = nm;
        g.is_start[idx] = static_cast<char>(start);
        g.launch[idx] = launch;
    }
    int m = 0;
    if (!(in >> tok >> m) || tok != "edges" || m < 0) return false;
    g.edges.resize(m);
    for (int k = 0; k < m; ++k) {
        if (!(in >> g.edges[k].src >> g.edges[k].dst >> g.edges[k].delay)) return false;
    }
    int p = 0;
    if (!(in >> tok >> p) || tok != "endpoints" || p < 0) return false;
    g.ep_node.resize(p);
    g.ep_required.resize(p);
    for (int k = 0; k < p; ++k) {
        if (!(in >> g.ep_node[k] >> g.ep_required[k])) return false;
    }
    return true;
}

}  // namespace

int main(int argc, char** argv) {
    Graph g;
    bool ok = false;
    if (argc > 1) {
        std::ifstream f(argv[1]);
        if (!f) {
            std::fprintf(stderr, "cannot open %s\n", argv[1]);
            return 1;
        }
        ok = read_graph(f, g);
    } else {
        ok = read_graph(std::cin, g);
    }
    if (!ok) {
        std::fprintf(stderr, "malformed graph input\n");
        return 1;
    }

    const int N = static_cast<int>(g.name.size());
    const double NEG_INF = -std::numeric_limits<double>::infinity();
    const double POS_INF = std::numeric_limits<double>::infinity();

    // Adjacency + in-degree.
    std::vector<std::vector<int>> out(N), in(N);
    std::vector<int> indeg(N, 0);
    for (int e = 0; e < static_cast<int>(g.edges.size()); ++e) {
        out[g.edges[e].src].push_back(e);
        in[g.edges[e].dst].push_back(e);
        indeg[g.edges[e].dst]++;
    }

    // Topological order (Kahn's algorithm).
    std::vector<int> order;
    order.reserve(N);
    std::vector<int> stack, deg = indeg;
    for (int i = 0; i < N; ++i)
        if (deg[i] == 0) stack.push_back(i);
    while (!stack.empty()) {
        int u = stack.back();
        stack.pop_back();
        order.push_back(u);
        for (int e : out[u])
            if (--deg[g.edges[e].dst] == 0) stack.push_back(g.edges[e].dst);
    }
    if (static_cast<int>(order.size()) != N) {
        std::fprintf(stderr, "combinational loop detected\n");
        return 2;
    }

    // Forward pass: latest arrival time, plus the critical incoming edge.
    std::vector<double> arrival(N, 0.0);
    std::vector<int> crit_edge(N, -1);
    for (int u : order) {
        if (g.is_start[u]) {
            arrival[u] = g.launch[u];
            continue;
        }
        double best = NEG_INF;
        int be = -1;
        for (int e : in[u]) {
            double a = arrival[g.edges[e].src] + g.edges[e].delay;
            if (a > best) {
                best = a;
                be = e;
            }
        }
        arrival[u] = (be == -1) ? 0.0 : best;
        crit_edge[u] = be;
    }

    // Backward pass: earliest required time.
    std::vector<double> required(N, POS_INF);
    for (int k = 0; k < static_cast<int>(g.ep_node.size()); ++k)
        required[g.ep_node[k]] = std::min(required[g.ep_node[k]], g.ep_required[k]);
    for (int i = N - 1; i >= 0; --i) {
        int u = order[i];
        double best = required[u];
        for (int e : out[u]) best = std::min(best, required[g.edges[e].dst] - g.edges[e].delay);
        required[u] = best;
    }

    // Worst negative slack over the endpoints.
    double wns = POS_INF;
    int worst = -1;
    for (int nd : g.ep_node) {
        double slack = required[nd] - arrival[nd];
        if (slack < wns) {
            wns = slack;
            worst = nd;
        }
    }

    std::printf("PySTA C++ core\n");
    std::printf("nodes %d  edges %d  endpoints %d\n", N,
                static_cast<int>(g.edges.size()), static_cast<int>(g.ep_node.size()));
    if (worst < 0) {
        std::printf("WNS n/a (no endpoints)\n");
        return 0;
    }
    std::printf("WNS %.6f\n", wns);
    std::printf("critical_endpoint %s\n", g.name[worst].c_str());
    std::printf("critical_path:\n");

    std::vector<int> chain;
    for (int u = worst; u != -1;) {
        chain.push_back(u);
        int e = crit_edge[u];
        u = (e == -1) ? -1 : g.edges[e].src;
    }
    std::reverse(chain.begin(), chain.end());
    for (size_t i = 0; i < chain.size(); ++i) {
        int nd = chain[i];
        double d = (i == 0) ? arrival[nd] : arrival[nd] - arrival[chain[i - 1]];
        std::printf("  %-18s delay %8.4f  arrival %8.4f\n", g.name[nd].c_str(), d, arrival[nd]);
    }
    return (wns < 0) ? 2 : 0;
}
