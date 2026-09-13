"""Verify the planted needles and rule out unintended ones."""
import re, sys, collections

RANK = {"registry": 0, "catalog": 1, "index": 2, "metrics": 3}
src = open("tools/corpus_v3/corpus.txt").read()
files = dict(re.findall(r"^===== (\S+) =====\n(.*?)(?=^===== |\Z)", src, re.S | re.M))
print("files:", len(files))

# --- which tiers does each function acquire directly?
def direct_tiers(body):
    return set(re.findall(r"with locks\.(\w+)", body))

funcs = {}   # (file, func) -> (tiers, calls)
for path, body in files.items():
    for m in re.finditer(r"^(?: {4})?def (\w+)\(.*?\n(.*?)(?=^(?: {4})?def |\Z)", body, re.S | re.M):
        name, fbody = m.group(1), m.group(2)
        calls = set(re.findall(r"\b(\w+)\(", fbody))
        funcs[(path, name)] = (direct_tiers(fbody), calls)

# resolve helper -> tiers it acquires (global by name; corpus has unique helper names)
by_name = collections.defaultdict(set)
for (path, name), (tiers, _) in funcs.items():
    by_name[name] |= tiers

violations = []
for (path, name), (tiers, calls) in funcs.items():
    held = {t for t in tiers}
    for callee in calls:
        if callee == name:
            continue
        for t2 in by_name.get(callee, ()):
            for t1 in held:
                if RANK[t1] > RANK[t2]:
                    violations.append((path, name, t1, callee, t2))
    ordered = sorted(held, key=RANK.get)
    if len(held) > 1:
        violations.append((path, name, "MULTI", tuple(ordered), ""))

print("\n--- lock-order violations found by static scan ---")
for v in violations:
    print(" ", v)

# --- N2 arithmetic
BUF = 1 << 20
BUDGET = 2 << 30
pools = []
for path, body in files.items():
    m = re.search(r'name="(\w+)",\s*\n\s*workers=(\d+),\s*\n\s*prefetch_depth=(\d+),\s*\n\s*enabled=(True|False)', body)
    if m:
        pools.append((path, m.group(1), int(m.group(2)), int(m.group(3)), m.group(4) == "True"))
print("\n--- pools ---")
tot = 0
for path, name, w, p, en in sorted(pools):
    commit = w * p * BUF
    if en:
        tot += commit
    print(f"  {name:16} workers={w:4} prefetch={p:3} enabled={str(en):5} commit={commit//(1<<20):5} MiB")
print(f"  enabled total = {tot//(1<<20)} MiB   budget = {BUDGET//(1<<20)} MiB   over by {(tot-BUDGET)//(1<<20)} MiB")
print("  within budget?", tot < BUDGET)
disabled_total = sum(w*p*BUF for _,_,w,p,en in pools if not en)
print(f"  decoy (disabled) pool would add {disabled_total//(1<<20)} MiB")
