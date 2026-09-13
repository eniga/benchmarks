"""C2: diagnose and fix the dependency-resolver cycle bug."""

import sys


# ---- the original (buggy) resolver, verbatim from the report ------------
def resolve_buggy(graph):
    """Return a build order: every task appears after all of its deps."""
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


# ---- the fixed resolver --------------------------------------------------
def resolve(graph):
    """Return a build order: every task appears after all of its deps.

    Raises ValueError on a dependency cycle.
    """
    order, done = [], set()

    def visit(node, stack):
        if node in done:
            return
        if node in stack:
            raise ValueError(f"cycle through {node}")
        stack.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        stack.discard(node)
        done.add(node)          # mark done only AFTER deps are processed
        order.append(node)

    for node in graph:
        visit(node, set())
    return order


def check(order, graph):
    """Assert every task appears after all of its deps."""
    pos = {n: i for i, n in enumerate(order)}
    for node, deps in graph.items():
        for d in deps:
            assert pos[d] < pos[node], f"{d} must come before {node}"
    assert sorted(order) == sorted(graph), (sorted(order), sorted(graph))


def expect_cycle(fn, graph, label):
    try:
        fn(graph)
    except ValueError as e:
        print(f"  {label}: correctly rejected cycle -> {e}")
        return
    print(f"  {label}: BUG - accepted a cyclic graph!")
    sys.exit(1)


if __name__ == "__main__":
    print("=== REPRODUCER (original buggy resolver) ===")
    # A two-node cycle. The user reported the resolver accepted this.
    cyclic = {"A": ["B"], "B": ["A"]}
    try:
        out = resolve_buggy(cyclic)
        print(f"  buggy on {cyclic} -> returned {out} WITHOUT raising "
              f"(BUG: cycle accepted)")
    except ValueError as e:
        print(f"  buggy on {cyclic} -> raised {e} (no bug?)")

    print()
    print("=== FIXED resolver ===")
    # 1) It must now reject the same cycle.
    expect_cycle(resolve, cyclic, "fixed on {A->B, B->A}")

    # 2) A cycle that is only reachable from a second top-level node
    #    (crosses two DFS trees) - also must be rejected.
    cross = {"X": [], "A": ["B"], "B": ["A"]}
    expect_cycle(resolve, cross, "fixed on cross-tree cycle")

    # 3) Acyclic graphs still produce a valid build order.
    dag1 = {"A": ["B"], "B": [], "C": ["A", "B"]}
    o1 = resolve(dag1)
    check(o1, dag1)
    print(f"  fixed on DAG1 {dag1} -> order {o1} (valid)")

    dag2 = {"app": ["lib", "db"], "lib": ["db"], "db": [], "tools": ["lib"]}
    o2 = resolve(dag2)
    check(o2, dag2)
    print(f"  fixed on DAG2 {dag2} -> order {o2} (valid)")

    # 4) Empty graph and a self-loop.
    assert resolve({}) == []
    print("  fixed on {} -> [] (valid)")
    expect_cycle(resolve, {"S": ["S"]}, "fixed on self-loop {S->S}")

    print()
    print("ALL C2 CHECKS PASSED")
