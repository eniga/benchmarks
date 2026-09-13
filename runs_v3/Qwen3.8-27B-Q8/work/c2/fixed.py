"""C2: fixed resolver + verification.

DIAGNOSIS
---------
In the original, ``seen`` is a *global visited* set that a node is added to the
instant it is first entered::

    stack.add(node)
    seen.add(node)      # marked "seen" before its deps are even explored

The cycle check is::

    if node in seen:    # <-- fires FIRST
        return
    if node in stack:   # <-- unreachable for back edges
        raise ValueError(...)

Because every node on the current DFS path is in ``stack`` *and* (simultaneously)
in ``seen``, a back edge -- the thing that actually identifies a cycle -- always
hits ``node in seen`` and returns early. The ``node in stack`` raise is dead
code, so **no cycle is ever detected**. Any cyclic project is silently accepted
and a bogus "build order" is emitted.

FIX
---
Use the standard three-colour DFS. A node is marked done (added to ``seen``)
only *after* it and all of its dependencies have been fully processed. The
current recursion path is tracked separately in ``stack`` (the "gray" set).
Then a back edge (a dependency that is still on the current path) is the only
thing that reaches the ``raise``, which is precisely a cycle.
"""

import random


def resolve(graph):
    """Return a build order for ``graph`` (node -> iterable of dependencies).

    Every dependency appears before the node that depends on it. Raises
    ValueError if the graph contains a cycle.
    """
    order = []
    seen = set()  # "black": fully processed (node and all its deps done)

    def visit(node, stack):
        if node in seen:
            return            # cross/forward edge: already fully ordered
        if node in stack:
            raise ValueError(f"cycle through {node}")  # back edge: a cycle
        stack.add(node)       # "gray": on the current recursion path
        for dep in graph.get(node, ()):
            visit(dep, stack)
        stack.discard(node)
        seen.add(node)        # mark done only after all deps are ordered
        order.append(node)

    for node in graph:
        visit(node, set())
    return order


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def is_valid_order(graph, order):
    if sorted(order) != sorted(graph.keys()):
        return False
    pos = {n: i for i, n in enumerate(order)}
    return all(pos[d] < pos[n] for n, deps in graph.items() for d in deps)


def has_cycle(graph):
    """Independent reference cycle check (Kahn's algorithm).

    An edge d -> n exists for each dependency d of n (d must be built before
    n). A cycle exists iff Kahn's algorithm cannot order every node.
    """
    from collections import deque
    nodes = set(graph.keys())
    for deps in graph.values():
        nodes.update(deps)
    indeg = {n: 0 for n in nodes}
    dependents = {n: [] for n in nodes}
    for n, deps in graph.items():
        for d in deps:
            dependents[d].append(n)
            indeg[n] += 1
    q = deque(n for n in nodes if indeg[n] == 0)
    seen = 0
    while q:
        n = q.popleft()
        seen += 1
        for m in dependents[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    return seen != len(nodes)


def main():
    ok = True

    # 1) The exact graphs from the reproducer.
    cyclic = [
        {"a": ["a"]},
        {"a": ["b"], "b": ["a"]},
        {"a": ["b"], "b": ["c"], "c": ["a"]},
        {"x": ["y"], "y": ["z"], "z": ["y"]},
    ]
    for g in cyclic:
        try:
            resolve(g)
            print(f"  FAIL: accepted cyclic {g}")
            ok = False
        except ValueError:
            print(f"  ok: rejected cyclic {sorted(g)}")

    dags = [
        {"app": ["lib", "db"], "lib": ["db"], "db": []},
        {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []},
        {"solo": []},
        {},
    ]
    for g in dags:
        order = resolve(g)
        good = is_valid_order(g, order)
        print(f"  {'ok' if good else 'FAIL'}: DAG {sorted(g)} -> {order}")
        ok = ok and good

    # 2) Randomized property test.
    rng = random.Random(1234)
    for trial in range(2000):
        n = rng.randint(1, 12)
        nodes = [f"n{i}" for i in range(n)]
        # random DAG: edges only go from higher index to lower index (acyclic)
        graph = {}
        for i, nd in enumerate(nodes):
            deps = [nodes[j] for j in range(i) if rng.random() < 0.4]
            graph[nd] = deps
        order = resolve(graph)
        if not is_valid_order(graph, order):
            print(f"  FAIL trial {trial}: bad order for DAG {graph}")
            ok = False
            break

    # 3) Differential test: on arbitrary random graphs, resolve()'s cycle
    #    verdict must agree with the independent Kahn reference.
    mismatches = 0
    n_cyclic = 0
    for trial in range(5000):
        n = rng.randint(1, 10)
        nodes = [f"n{i}" for i in range(n)]
        graph = {nd: [] for nd in nodes}
        for nd in nodes:
            for other in nodes:
                if other != nd and rng.random() < 0.25:
                    graph[nd].append(other)
        should_cycle = has_cycle(graph)
        n_cyclic += should_cycle
        try:
            resolve(graph)
            detected = False
        except ValueError:
            detected = True
        if detected != should_cycle:
            mismatches += 1
            if mismatches <= 5:
                print(f"  FAIL trial {trial}: detected={detected} "
                      f"reference={should_cycle} graph={graph}")
    print(f"  differential: 5000 random graphs ({n_cyclic} cyclic), "
          f"{mismatches} mismatches")
    ok = ok and mismatches == 0

    print("\n" + ("ALL C2 CHECKS PASSED" if ok else "C2 CHECKS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
