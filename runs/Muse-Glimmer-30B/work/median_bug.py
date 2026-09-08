def median_of_sorted_arrays(a, b):
    if len(a) > len(b):
        a, b = b, a
    lo, hi = 0, len(a)
    while lo <= hi:
        i = (lo + hi) // 2
        j = (len(a) + len(b) + 1) // 2 - i
        left_a  = a[i-1] if i > 0 else float('-inf')
        right_a = a[i]   if i < len(a) else float('inf')
        left_b  = b[j-1] if j > 0 else float('-inf')
        right_b = b[j]   if j < len(b) else float('inf')
        if left_a <= right_b and left_b <= right_a:
            if (len(a) + len(b)) % 2:
                return max(left_a, left_b)
            return (max(left_a, left_b) + min(right_a, right_b)) / 2
        elif left_a > right_b:
            hi = i - 1
        else:
            lo = i + 1

# Reproduce with large ints
a = [2**60, 2**60+1]
b = [2**60+2, 2**60+3]
print('buggy', median_of_sorted_arrays(a,b))

def median_fixed(a,b):
    if len(a) > len(b):
        a,b = b,a
    lo,hi = 0,len(a)
    while lo<=hi:
        i=(lo+hi)//2
        j=(len(a)+len(b)+1)//2 - i
        left_a = a[i-1] if i>0 else None
        right_a = a[i] if i<len(a) else None
        left_b = b[j-1] if j>0 else None
        right_b = b[j] if j<len(b) else None
        # define comparison helpers
        def le(x,y):
            if x is None: return True
            if y is None: return False
            return x <= y
        def ge(x,y):
            if x is None: return False
            if y is None: return True
            return x >= y
        # Actually need proper logic
        # Simpler: use sentinel ints
        left_a_s = a[i-1] if i>0 else -10**30
        right_a_s = a[i] if i<len(a) else 10**30
        left_b_s = b[j-1] if j>0 else -10**30
        right_b_s = b[j] if j<len(b) else 10**30
        if left_a_s <= right_b_s and left_b_s <= right_a_s:
            if (len(a)+len(b))%2:
                return max(left_a_s,left_b_s)
            return (max(left_a_s,left_b_s)+min(right_a_s,right_b_s))/2
        elif left_a_s > right_b_s:
            hi=i-1
        else:
            lo=i+1

print('fixed', median_fixed(a,b))
