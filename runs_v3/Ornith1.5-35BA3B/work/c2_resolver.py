"""C2: the dependency resolver bug, a reproducer, and the fix.

The shipped implementation marks a node as "seen" the instant it is first
ENTERED (before its dependencies are explored) and starts each top-level DFS
with a fresh ``stack``. A back-edge to a node that is still being processed is
therefore swallowed by the ``if node in seen: return`` check and never reaches
the ``if node in stack`` cycle check. Cycles are silently accepted.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def resolve_original(graph):
    """The shipped implementation (buggy)."""
    order, seen = [], set()

    def visit(node, stack):
        if node in seen:
            return
        if node in stack:
            raise ValueError(f"cycle through {node}")
        stack.add(node)
        seen.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        order.append(node)
        stack.discard(node)

    for node in graph:
        visit(node, set())
    return order


def resolve_fixed(graph):
    """Fixed implementation.

    Move ``visited.add(node)`` to AFTER the dependency loop so a node is only
    marked permanently done once its whole subtree is explored. ``stack`` still
    tracks the in-progress path, so a back-edge now reaches the
    ``if node in stack`` check and raises. The ``if node in visited`` check
    still short-circuits fully-processed nodes (so diamonds are not rejected).
    """
    order, visited = [], set()

    def visit(node, stack):
        if node in visited:
            return
        if node in stack:
            raise ValueError(f"cycle through {node}")
        stack.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        order.append(node)
        visited.add(node)
        stack.discard(node)

    for node in graph:
        visit(node, set())
    return order


def topologically_valid(graph, order):
    """True if every task appears after all of its deps in ``order``."""
    pos = {node: i for i, node in enumerate(order)}
    if len(pos) != len(order):
        return False  # duplicate / missing node
    for node, deps in graph.items():
        for dep in deps:
            if pos[dep] > pos[node]:
                return False
    return True


def main():
    print("=== Reproducing the reported bug: a cycle that is accepted ===")
    cyclic = {"a": ["b"], "b": ["a"]}
    print("graph:", cyclic)
    try:
        orig = resolve_original(cyclic)
        print("ORIGINAL accepted the cycle -> build order =", orig,
              "  <-- BUG: a self-referential project was accepted")
    except ValueError as e:
        print("ORIGINAL raised:", e)

    print()
    print("=== The fix rejects the same graph ===")
    try:
        print("FIXED returned build order =", resolve_fixed(cyclic), "(unexpected)")
    except ValueError as e:
        print("FIXED raised ValueError:", e)

    print()
    print("=== Longer cycles are also rejected by the fix ===")
    for cyc in ({"a": ["b"], "b": ["c"], "c": ["a"]},
                {"a": ["b"], "b": ["c"], "c": ["d"], "d": ["a"], "e": ["a"]}):
        try:
            print("  ORIGINAL", cyc, "->", resolve_original(cyc), "(accepted, BUG)")
        except ValueError as e:
            print("  ORIGINAL", cyc, "-> raised:", e)
        try:
            print("  FIXED   ", cyc, "-> accepted (unexpected)")
        except ValueError as e:
            print("  FIXED   ", cyc, "-> raised ValueError:", e)

    print()
    print("=== Valid DAGs still resolve to a valid topological order ===")
    dags = [
        {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []},
        {"a": ["b"], "b": []},
        {"x": [], "y": ["x"], "z": ["y", "x"]},
        {"only": []},
        {"a": ["b", "c", "d"], "b": ["e"], "c": ["e"], "d": ["e"], "e": []},
    ]
    all_ok = True
    for g in dags:
        o = resolve_original(g)
        f = resolve_fixed(g)
        same = (o == f)
        valid = topologically_valid(g, f)
        status = "OK" if (same and valid) else "PROBLEM"
        if not (same and valid):
            all_ok = False
        print(f"{status}  graph={g}")
        print(f"       original={o}  fixed={f}  valid_topo={valid}")
    print("All DAG outputs identical and valid:", all_ok)


if __name__ == "__main__":
    main()
