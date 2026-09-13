"""Task C2 - the dependency resolver, as found, and fixed.

resolve_original is the code exactly as it was handed over.
resolve_fixed is the corrected version.
"""

from __future__ import annotations


# --------------------------------------------------------------------------
# as found
# --------------------------------------------------------------------------
def resolve_original(graph):
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


# --------------------------------------------------------------------------
# fixed
# --------------------------------------------------------------------------
def resolve_fixed(graph):
    """Return a build order: every task appears after all of its deps.

    Raises ValueError on any cycle (including self-dependencies).

    Three-colour DFS:
      * ``stack``  - nodes on the current path (grey).  Reaching one means the
        graph is not acyclic.  Checked *first*, so a node that is on the path
        can never be mistaken for a finished one.
      * ``done``   - nodes whose whole sub-graph is already known acyclic and
        ordered (black).  Re-entering one is a legitimate memo hit, which is
        what keeps the shared-across-roots traversal linear.
    A node is marked done only after all of its dependencies have been
    processed, and the reservation is removed from the path on the way out.
    """
    order: list = []
    done: set = set()

    def visit(node, stack):
        if node in stack:
            raise ValueError(f"cycle through {node}")
        if node in done:
            return
        stack.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        stack.discard(node)
        done.add(node)
        order.append(node)

    for node in graph:
        visit(node, set())
    return order


# --------------------------------------------------------------------------
# helpers used by the reproducer
# --------------------------------------------------------------------------
def order_violations(order, graph):
    """Edges (node -> dep) where dep is not built before node."""
    where = {node: i for i, node in enumerate(order)}
    bad = []
    for node in graph:
        for dep in graph.get(node, ()):
            if dep not in where:
                bad.append((node, dep, "dep missing from order"))
            elif where[dep] >= where[node]:
                bad.append((node, dep, f"dep at {where[dep]} not before {where[node]}"))
    return bad


def instrumented_original(graph):
    """Same traversal as resolve_original, counting which branch fires."""
    stats = {"seen_hit": 0, "stack_hit": 0, "cycle_detected": 0}
    order, seen = [], set()

    def visit(node, stack):
        if node in seen:
            stats["seen_hit"] += 1
            return
        if node in stack:
            stats["stack_hit"] += 1
            stats["cycle_detected"] += 1
            raise ValueError(f"cycle through {node}")
        stack.add(node)
        seen.add(node)
        for dep in graph.get(node, ()):
            visit(dep, stack)
        order.append(node)
        stack.discard(node)

    for node in graph:
        visit(node, set())
    return order, stats
