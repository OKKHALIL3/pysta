"""Cross-check the C++ core against the Python engine.

Builds cpp/sta_core.cpp, feeds it the resolved graph the Python engine exports,
and confirms both implementations agree on worst negative slack and the critical
endpoint. Skipped automatically if no C++ compiler is available.
"""

import os
import re
import shutil
import subprocess
import tempfile

import pytest

from conftest import EXAMPLES, ROOT
from pysta.export_graph import to_resolved_graph
from pysta.graph import build_graph
from pysta.liberty import load_liberty
from pysta.netlist import load_verilog
from pysta.sdc import load_sdc
from pysta.timing import analyze

CXX = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")


@pytest.mark.skipif(CXX is None, reason="no C++ compiler available")
def test_cpp_core_matches_python():
    src = os.path.join(ROOT, "cpp", "sta_core.cpp")
    with tempfile.TemporaryDirectory() as tmp:
        binary = os.path.join(tmp, "sta_core")
        subprocess.run([CXX, "-std=c++17", "-O2", "-o", binary, src], check=True)

        lib = load_liberty(os.path.join(EXAMPLES, "tiny.lib"))
        nl = load_verilog(os.path.join(EXAMPLES, "pipe.v"))
        sdc = load_sdc(os.path.join(EXAMPLES, "pipe.sdc"))
        graph = build_graph(nl, lib)
        res = analyze(graph, lib, sdc)

        text = to_resolved_graph(graph, res, sdc.default_input_slew)
        out = subprocess.run(
            [binary], input=text, capture_output=True, text=True, check=True
        ).stdout

        wns = re.search(r"WNS\s+(-?\d+\.?\d*)", out)
        endpoint = re.search(r"critical_endpoint\s+(\S+)", out)
        assert wns and endpoint, out
        assert float(wns.group(1)) == pytest.approx(res.wns, abs=1e-4)
        assert endpoint.group(1) == res.critical_endpoint
