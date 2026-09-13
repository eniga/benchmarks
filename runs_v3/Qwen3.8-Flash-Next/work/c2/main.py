"""Task C2 reproducer / regression harness."""

from __future__ import annotations

import random
import sys

from resolver import (instrumented_original, order_violations, resolve_fixed,
                      resolve_original)


def show(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def run(label, graph):
    print(f"\n{label}")
    print(f"  input: {graph}")
    try:
        order = resolve_original(graph)
    except ValueError as exc:
        print(f"  resolve_original : ValueError({exc})")
    else:
        bad = order_violations(order, graph)
        print(f"  resolve_original : ACCEPTED -> {order}")
        print(f"                     dependency violations: {bad if bad else 'none'}")
    try:
        fixed = resolve_fixed(graph)
    except ValueError as exc:
        print(f"  resolve_fixed    : ValueError({exc})")
    else:
        bad = order_violations(fixed, graph)
        print(f"  resolve_fixed    : {fixed}  (violations: {bad if bad else 'none'})")


# --------------------------------------------------------------------------
show("1. the reported project: accepted by the shipped resolver")
PROJECT = {
    "app": ["api", "ui"],
    "api": ["model"],
    "ui": ["theme"],
    "model": ["codegen", "logger"],
    "codegen": ["model"],          # <-- model <-> codegen
    "logger": [],
    "theme": [],
}
run("project graph (model depends on codegen, codegen depends on model)", PROJECT)

show("2. minimal reductions of the same defect")
run("two-node cycle  {'a': ['b'], 'b': ['a']}", {"a": ["b"], "b": ["a"]})
run("self cycle      {'a': ['a']}", {"a": ["a"]})
run("cycle behind a finished node  {'x': ['y'], 'y': [], 'p': ['q'], 'q': ['p']}",
    {"x": ["y"], "y": [], "p": ["q"], "q": ["p"]})

show("3. why: the cycle branch is unreachable")
graphs = [PROJECT, {"a": ["b"], "b": ["a"]}, {"a": ["a"]},
          {"a": ["b", "c"], "b": ["c"], "c": ["b"]},
          {"a": ["b"], "b": ["c"], "c": ["d"], "d": ["b"]}]
tot_seen_hit = tot_stack_hit = 0
for g in graphs:
    _, stats = instrumented_original(g)
    tot_seen_hit += stats["seen_hit"]
    tot_stack_hit += stats["stack_hit"]
    print(f"  {str(g):<70} seen-hits={stats['seen_hit']} stack-hits={stats['stack_hit']}")
print(f"  total over {len(graphs)} cyclic graphs: 'node in seen' fired {tot_seen_hit} times, "
      f"'node in stack' fired {tot_stack_hit} times")
print("  resolve_original adds a node to `seen` *before* recursing, so every node")
print("  that is on the current path is already in `seen`; the `if node in seen:")
print("  return` test above it always wins and `raise ValueError(cycle ...)` is dead code.")

show("4. sweep: does the fix regress correct graphs / catch cycles?")
rng = random.Random(20260913)


def rand_dag(n, p=0.25):
    nodes = [f"t{i}" for i in range(n)]
    g = {v: [] for v in nodes}
    for i, v in enumerate(nodes):
        for w in nodes[i + 1:]:
            if rng.random() < p:
                g[v].append(w)
    return g


def has_cycle_kahn(graph):
    """Independent reference check: Kahn's algorithm over keys and values."""
    nodes = set(graph)
    for deps in graph.values():
        nodes.update(deps)
    indeg = {n: 0 for n in nodes}
    for deps in graph.values():
        for d in deps:
            indeg[d] += 1
    q = [n for n in nodes if indeg[n] == 0]
    seen = 0
    while q:
        n = q.pop()
        seen += 1
        for dep in graph.get(n, ()):        # drop edge n -> dep
            indeg[dep] -= 1
            if indeg[dep] == 0:
                q.append(dep)
    return seen != len(nodes)


def add_cycle(g):
    """Flip an existing edge u->v into v->u as well: guarantees a 2-cycle."""
    edges = [(u, v) for u, vs in g.items() for v in vs]
    if not edges:
        node = next(iter(g))
        g[node].append(node)               # self-loop
        return g
    u, v = edges[rng.randrange(len(edges))]
    g[v].append(u)
    return g


dag_ok_orig = dag_ok_fixed = dag_kahn_flagged = 0
DAGS = 300
for _ in range(DAGS):
    g = rand_dag(rng.randint(2, 14))
    if has_cycle_kahn(g):
        dag_kahn_flagged += 1
    try:
        o1 = resolve_original(g)
        o2 = resolve_fixed(g)
    except ValueError:
        continue
    if not order_violations(o1, g):
        dag_ok_orig += 1
    if not order_violations(o2, g):
        dag_ok_fixed += 1
print(f"  random acyclic graphs: {DAGS}; Kahn flagged {dag_kahn_flagged} as cyclic; "
      f"orders valid for all nodes/edges -> original {dag_ok_orig}/{DAGS}, "
      f"fixed {dag_ok_fixed}/{DAGS}")

CYC = 300
det_orig = det_fixed = 0
kahn_cyclic = 0
bad_fixed = []
for _ in range(CYC):
    g = add_cycle(rand_dag(rng.randint(2, 14)))
    if not has_cycle_kahn(g):
        bad_fixed.append(("kahn says acyclic", g))
    else:
        kahn_cyclic += 1
    try:
        resolve_original(g)
    except ValueError:
        det_orig += 1
    try:
        resolve_fixed(g)
    except ValueError:
        det_fixed += 1
print(f"  random graphs with a flipped edge: {CYC}; Kahn agrees {kahn_cyclic} of them "
      f"are cyclic ({len(bad_fixed)} disputed)")
print(f"  rejected by resolver -> original {det_orig}/{CYC}, fixed {det_fixed}/{CYC}")

# a DAG and its cyclic twin, side by side
DAG = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}
CYCTWIN = {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": ["b"]}
run("dag   {'a': ['b','c'], 'b': ['d'], 'c': ['d'], 'd': []}", DAG)
run("cyclic twin (d -> b added)", CYCTWIN)

show("5. other behaviour the fix keeps / changes deliberately")
# nodes reachable only as values, never as keys
G2 = {"a": ["b"]}
run("dependency missing as a key: {'a': ['b']}", G2)
print(f"  fixed recursion limit untouched; sys.getrecursionlimit()={sys.getrecursionlimit()}")
deep = {f"n{i}": [f"n{i+1}"] for i in range(198)} | {f"n199": []}
print(f"  deep chain of 199 nodes -> {resolve_fixed(deep)[:3]}... len={len(resolve_fixed(deep))}")
