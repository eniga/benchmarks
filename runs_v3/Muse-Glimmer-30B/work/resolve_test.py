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

# Reproduce
graph_cycle = {'A': ['B'], 'B': ['A']}
print("Buggy resolver output:")
try:
    out = resolve_buggy(graph_cycle)
    print(out)
except ValueError as e:
    print("Raised:", e)

print("Fixed resolver output:")
try:
    out = resolve_fixed(graph_cycle)
    print(out)
except ValueError as e:
    print("Raised:", e)
