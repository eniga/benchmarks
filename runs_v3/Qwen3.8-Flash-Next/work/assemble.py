"""Assemble the C section by inlining verbatim file contents at placeholders."""

import pathlib

ROOT = pathlib.Path("/tmp/bench_work")
MAP = {
    "@@POOL_PY@@": ("c1/pool.py", "python"),
    "@@TEST_POOL_PY@@": ("c1/test_pool.py", "python"),
    "@@C1_TESTS@@": ("c1/c1_tests_final.txt", None),
    "@@C1_BURSTCTRL@@": ("c1/c1_burst_control.txt", None),
    "@@C1_FAIRNESS@@": ("c1/c1_fairness.txt", None),
    "@@C1_NAIVE@@": ("c1/c1_naive.txt", None),
    "@@C2_RESOLVER@@": ("c2/resolver.py", "python"),
    "@@C2_MAIN@@": ("c2/c2_out.txt", None),
    "@@C2_DEPTH@@": ("c2/c2_depth.txt", None),
    "@@C3_MEMOIZE@@": ("c3/memoize_as_found.py", "python"),
    "@@C3_CHECK@@": ("c3/c3_out.txt", None),
    "@@C4_PY@@": ("c4/c4.py", "python"),
    "@@C4_OUT@@": ("c4/c4_out.txt", None),
}

text = (ROOT / "r_part_e.md").read_text()
for key, (rel, lang) in MAP.items():
    body = (ROOT / rel).read_text().rstrip("\n")
    assert "```" not in body, f"{rel} contains a fence"
    fence = "```" + (lang or "")
    text = text.replace(key, f"{fence}\n{body}\n```")
assert "@@>" not in text and "@@" not in text, "unsubstituted placeholder"
(ROOT / "r_part_e_final.md").write_text(text)

parts = ["r_part_a.md", "r_part_b.md", "r_part_c.md", "r_part_d.md",
         "r_part_e_final.md", "r_part_f.md"]
out = []
for p in parts:
    out.append((ROOT / p).read_text().rstrip("\n"))
final = "\n\n".join(out) + "\n"
pathlib.Path("/Users/enigaahiante/Projects/benchmarks/testsuites/results.md").write_text(final)
print("wrote results.md, lines:", final.count("\n"))
