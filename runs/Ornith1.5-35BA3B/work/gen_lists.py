"""Generate canonical spelled-out number lists and verify/patch results.md."""

ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight",
        "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
        "sixteen", "seventeen", "eighteen", "nineteen"]  # index 0..19
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
        "eighty", "ninety"]  # index 2..9


def below_hundred(n):
    if n < 20:
        return ONES[n]
    if n % 10 == 0:
        return TENS[n // 10]
    return TENS[n // 10] + "-" + ONES[n % 10]


def num_to_words(n):
    if n < 100:
        return below_hundred(n)
    if n < 1000:
        h, r = divmod(n, 100)
        if r == 0:
            return f"{ONES[h]} hundred"
        return f"{ONES[h]} hundred {below_hundred(r)}"
    raise ValueError(n)


def block(lo, hi):
    return "\n".join(f"{n}. {num_to_words(n)}" for n in range(lo, hi + 1))


def patch_str(src, heading_after_start, heading_end, text):
    start = src.index(f"## {heading_after_start}\n") + len(f"## {heading_after_start}\n")
    end = src.index(f"\n## {heading_end}\n")
    return src[:start] + text + src[end:]


def extract(src, heading):
    s = src.index(f"## {heading}\n") + len(f"## {heading}\n")
    e = src.index("\n## ", s)
    return src[s:e].splitlines()


if __name__ == "__main__":
    import sys

    path = "/Users/enigaahiante/Projects/benchmarks/testsuites/results.md"
    src = open(path).read()

    checks = {
        "R1": (1, 300, "R2"),
        "F1a": (1, 10, "F1b"),
        "F1b": (1, 50, "F1c"),
        "F1c": (1, 300, "A1"),
    }

    def mismatches(heading, lo, hi):
        got = extract(src, heading)
        exp = block(lo, hi).splitlines()
        out = [(i + 1, g, e) for i, (g, e) in enumerate(zip(got, exp)) if g != e]
        if len(got) != len(exp):
            out.append(("LEN", len(got), len(exp)))
        return out

    before = {h: mismatches(h, lo, hi) for h, (lo, hi, _e) in checks.items()}
    if before:
        print("MISMATCHES BEFORE PATCH:")
        for h, m in before.items():
            print(f"  {h}: {len(m)}; sample: {m[:6]}")

    # Patch every list to canonical, threading src through each step.
    src = patch_str(src, "R1", "R2", block(1, 300))
    src = patch_str(src, "F1a", "F1b", block(1, 10))
    src = patch_str(src, "F1b", "F1c", block(1, 50))
    src = patch_str(src, "F1c", "A1", block(1, 300))
    open(path, "w").write(src)
    print("Patched all lists to canonical form.")

    after = {}
    for h, (lo, hi, _e) in checks.items():
        m = mismatches(h, lo, hi)
        if m:
            after[h] = m
    if after:
        print("MISMATCHES AFTER PATCH:")
        for h, m in after.items():
            print(f"  {h}: {len(m)}; sample: {m[:6]}")
        sys.exit(1)
    print("All lists correct AFTER patch.")
