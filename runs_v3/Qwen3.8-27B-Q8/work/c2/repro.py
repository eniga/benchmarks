"""C2: reproduce the cycle-detection bug in the dependency resolver."""

def resolve(graph):
    """Return a build order for ``graph`` (node -> iterable of dependencies).

    Every dependency must appear before the node that depends on it.
    Raises ValueError if the graph contains a cycle.
    """
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


def expect_cycle(graph, label):
    try:
        out = resolve(graph)
    except ValueError as e:
        print(f"  {label}: correctly raised ValueError({e})")
        return True
    print(f"  {label}: BUG -- accepted a cyclic graph, returned {out}")
    return False


def expect_ok(graph, label):
    out = resolve(graph)
    # verify it's a valid topological order (every dep before its dependent)
    pos = {n: i for i, n in enumerate(out)}
    ok = all(pos[d] < pos[n] for n, deps in graph.items() for d in deps)
    print(f"  {label}: returned {out}  (valid topo order: {ok})")
    return ok


if __name__ == "__main__":
    print("Cyclic graphs (should all be REJECTED with ValueError):")
    r = []
    r.append(expect_cycle({"a": ["a"]}, "self-loop a->a"))
    r.append(expect_cycle({"a": ["b"], "b": ["a"]}, "2-cycle a<->b"))
    r.append(expect_cycle({"a": ["b"], "b": ["c"], "c": ["a"]},
                          "3-cycle a->b->c->a"))
    r.append(expect_cycle({"x": ["y"], "y": ["z"], "z": ["y"]},
                          "2-cycle y<->z with tail x"))
    print(f"  => {sum(r)}/{len(r)} cycles correctly rejected "
          f"({len(r) - sum(r)} wrongly ACCEPTED)")

    print("\nAcyclic graphs (should all be ACCEPTED, valid order):")
    o = []
    o.append(expect_ok({"app": ["lib", "db"], "lib": ["db"], "db": []},
                       "diamond DAG"))
    o.append(expect_ok({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []},
                       "shared dependency"))
    o.append(expect_ok({"solo": []}, "single node"))
    print(f"  => {sum(o)}/{len(o)} DAGs correctly accepted")
