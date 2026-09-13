"""Side-by-side recursion limit behaviour: original vs fixed."""

import sys

from resolver import resolve_fixed, resolve_original

for n in (199, 999, 1000, 2000):
    graph = {f"n{i}": [f"n{i+1}"] for i in range(n)} | {f"n{n}": []}
    row = [f"chain of {n} edges"]
    for name, fn in (("original", resolve_original), ("fixed", resolve_fixed)):
        try:
            order = fn(graph)
            row.append(f"{name}: ok, order length {len(order)}")
        except RecursionError:
            row.append(f"{name}: RecursionError")
        except Exception as exc:                                # pragma: no cover
            row.append(f"{name}: {type(exc).__name__}: {exc}")
    print(f"  {row[0]:<22} | {row[1]} | {row[2]}")
print(f"  sys.getrecursionlimit() = {sys.getrecursionlimit()}")
