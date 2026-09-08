nums=['zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen']
tens=['','','twenty','thirty','forty','fifty','sixty','seventy','eighty','ninety']
def spell(n):
    if n==0:
        return 'zero'
    if n<20:
        return nums[n]
    if n<100:
        t=n//10
        u=n%10
        return tens[t]+('-'+nums[u] if u else '')
    if n<1000:
        h=n//100
        r=n%100
        s=nums[h]+' hundred'
        if r:
            s+=' '+spell(r)
        return s
for upto in [10,50,300]:
    with open(f'work/list{upto}.txt','w') as f:
        for i in range(1,upto+1):
            f.write(f"{i}. {spell(i)}\n")
