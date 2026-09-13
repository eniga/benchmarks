"""C2: reproduce the resolver accepting a cyclic graph, then verify the fix."""

# --- original (buggy) -------------------------------------------------------
def resolve_buggy(graph):
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


# --- fixed: check the current DFS stack before the global seen set ----------
def resolve_fixed(graph):
    order, seen = [], set()

    def visit(node, stack):
        if node in stack:
            raise ValueError(f"cycle through {node}")
        if node in seen:
            return
        stack.add(node)
        seen.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        order.append(node)
        stack.discard(node)

    for node in graph:
        visit(node, set())
    return order


REPRO = {"a": ["b"], "b": ["a"]}  # a depends on b, b depends on a

print("input:", REPRO)
print("buggy:", end=" ")
try:
    print("accepted, order =", resolve_buggy(REPRO))
except ValueError as e:
    print("rejected:", e)
print("fixed:", end=" ")
try:
    print("accepted, order =", resolve_fixed(REPRO))
except ValueError as e:
    print("rejected:", e)

# sanity: acyclic graphs still resolve, in a valid build order
AC = {"app": ["lib", "util"], "lib": ["util"], "util": []}
o = resolve_fixed(AC)
print("acyclic:", o, "valid:", all(o.index(d) < o.index(n) for n in AC for d in AC[n]))

# cycle not reachable from the first top-level node
AC2 = {"x": [], "a": ["b"], "b": ["a"]}
print("late cycle:", end=" ")
try:
    print("accepted:", resolve_fixed(AC2))
except ValueError as e:
    print("rejected:", e)
