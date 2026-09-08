"""Reproduce the 64-bit record ID bug in the original median function."""

from median_original import median_of_sorted_arrays

# Two 63-bit record IDs (both < 2**63).
a = [9223372036854775805]
b = [9223372036854775807]

got = median_of_sorted_arrays(a, b)
want = (a[0] + b[0]) // 2  # exact integer median

print("input a =", a)
print("input b =", b)
print("original returned:", got, type(got).__name__, " (exactly", int(got), ")")
print("correct median  :", want, type(want).__name__)
print("exact error     :", int(got) - want)
print("got == want?    ", got == want)

# Show the float conversion that causes it:
print()
print("float(a[0])          =", float(a[0]))
print("float(b[0])          =", float(b[0]))
print("float(a[0] + b[0])   =", float(a[0] + b[0]))
print("exact a[0] + b[0]    =", a[0] + b[0])
print("(exact sum) / 2      =", (a[0] + b[0]) / 2)

# A second case: the two IDs round to the SAME float64.
a2 = [4611686018427387905]
b2 = [4611686018427387907]
got2 = median_of_sorted_arrays(a2, b2)
want2 = (a2[0] + b2[0]) // 2
print()
print("second case: original returned:", int(got2), " correct:", want2,
      " (exact error:", int(got2) - want2, ")")
