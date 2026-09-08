def median_bug(a,b):
    if len(a)>len(b): a,b=b,a
    lo,hi=0,len(a)
    while lo<=hi:
        i=(lo+hi)//2
        j=(len(a)+len(b)+1)//2 - i
        left_a=a[i-1] if i>0 else float('-inf')
        right_a=a[i] if i<len(a) else float('inf')
        left_b=b[j-1] if j>0 else float('-inf')
        right_b=b[j] if j<len(b) else float('inf')
        if left_a<=right_b and left_b<=right_a:
            if (len(a)+len(b))%2:
                return max(left_a,left_b)
            return (max(left_a,left_b)+min(right_a,right_b))/2
        elif left_a>right_b:
            hi=i-1
        else:
            lo=i+1

def median_true(a,b):
    merged=sorted(a+b)
    n=len(merged)
    if n%2==1:
        return merged[n//2]
    else:
        return (merged[n//2-1]+merged[n//2])/2

import random
for _ in range(100000):
    n=random.randint(1,10)
    m=random.randint(1,10)
    # generate large ints
    a=sorted([random.randint(2**60,2**62) for _ in range(n)])
    b=sorted([random.randint(2**60,2**62) for _ in range(m)])
    bug=median_bug(a,b)
    true=median_true(a,b)
    if bug!=true:
        print('found',a,b,bug,true)
        break
else:
    print('none')
