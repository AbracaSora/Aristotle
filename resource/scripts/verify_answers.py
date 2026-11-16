"""Independent arithmetic/algorithm checks for all four subjects.

Run directly for a read-only summary; build_resources.py includes all results in one report.
The stem+options digest in answer_cases.json binds each calculation to the
reviewed question inputs. Editing a question requires rechecking its case;
Checks never refresh those digests or change a canonical answer.
"""
import argparse
import heapq
import itertools
from collections import deque
from fractions import Fraction
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import struct

ROOT=Path(__file__).resolve().parents[1]
FOLDERS={'DS':'data-structures','CO':'computer-organization','OS':'operating-systems','CN':'computer-networks'}


def binding(question):
    return hashlib.sha256(json.dumps([question['stem'],question['options']],ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def replace_trace(sequence,capacity,lru=False):
    queue=[]
    victims=[]
    for value in sequence:
        if value in queue:
            if lru:
                queue.remove(value)
                queue.append(value)
            continue
        if len(queue)==capacity:
            victims.append(queue.pop(0))
        queue.append(value)
    return victims


def crc(data,generator):
    degree=len(generator)-1
    value=int(data,2)<<degree
    divisor=int(generator,2)
    while value.bit_length()>=divisor.bit_length():
        value ^= divisor<<(value.bit_length()-divisor.bit_length())
    return format(value,f'0{degree}b')


def bit_stuff(bits):
    out=''
    run=0
    for bit in bits:
        out+=bit
        run=run+1 if bit=='1' else 0
        if run==5:
            out+='0'
            run=0
    return out


def rr_completion(jobs,quantum):
    queue=deque(jobs)
    remaining=dict(jobs)
    now=0
    finished={}
    while queue:
        name,_=queue.popleft()
        amount=min(quantum,remaining[name])
        remaining[name]-=amount
        now+=amount
        if remaining[name]:
            queue.append((name,remaining[name]))
        else:
            finished[name]=now
    return finished


def safe_order(available,allocated,maxima):
    pending=list(allocated)
    order=[]
    while pending:
        suitable=next((name for name in pending if maxima[name]-allocated[name]<=available),None)
        if suitable is None:
            raise AssertionError('No safe sequence')
        available+=allocated[suitable]
        pending.remove(suitable)
        order.append(suitable)
    return order


def shortest_path(edges,start,target):
    nodes={n for a,b,_ in edges for n in (a,b)}
    distance={n:math.inf for n in nodes}
    distance[start]=0
    unvisited=set(nodes)
    while unvisited:
        node=min(unvisited,key=distance.get)
        unvisited.remove(node)
        for a,b,cost in edges:
            if node in (a,b):
                other=b if node==a else a
                distance[other]=min(distance[other],distance[node]+cost)
    return distance[target]


def calculations():
    cases=[]
    def add(key,value,method):
        cases.append(dict(question_id='KEW-'+key,computed_answer=str(value),method=method))
    add('CO-performance-01',f'{1.8e8*2/.3/1e9:g} GHz','cycles / allowed time')
    add('CO-performance-02',f'{1/.25:g}倍','Amdahl limit with unaccelerated fraction .25')
    add('CO-performance-04',f'{2e8/.5/1e6:g}','instruction count / time / one million')
    add('CO-radix-01',int('101101',2),'binary place values')
    add('CO-radix-02',format(int('3A',16),'08b'),'hex to binary conversion')
    add('CO-radix-04',-int('0000101',2),'sign-magnitude negative sign and magnitude')
    add('CO-signed-01',int('11110110',2)-256,'8-bit two complement interpretation')
    add('CO-signed-03',f'{int("10000000",2)}和{int("10000000",2)-256}','unsigned and signed views')
    add('CO-alu-01',f'{(1+1+1)%2}和{(1+1+1)//2}','full adder sum and carry')
    add('CO-alu-03',format(0b1010^0b1100,'04b'),'bitwise exclusive or')
    total=100+60
    add('CO-addsub-01',format(total&255,'08b')+'，'+('发生' if total>127 else '不发生')+'有符号溢出','two positive signed operands overflow signed range')
    unsigned=0b11110000+0b00110000
    signed=(0b11110000-256)+0b00110000
    add('CO-addsub-02',('有' if unsigned>255 else '无')+'最高位进位，'+('没有' if -128<=signed<=127 else '有')+'有符号溢出','independent unsigned carry and signed overflow predicates')
    add('CO-muldiv-01',f'{(255*4095).bit_length()}位','maximum product bit length')
    add('CO-muldiv-02',-12>>1,'arithmetic right shift')
    add('CO-muldiv-04','、'.join(str(13<<i) for i in range(4) if 11&(1<<i)),'enumerate set-bit partial products')
    add('CO-float-format-01',str(struct.unpack('!f',(127<<23).to_bytes(4,'big'))[0]),'decode IEEE binary32 bits')
    add('CO-float-format-02',str(struct.unpack('!f',((1<<31)|(128<<23)).to_bytes(4,'big'))[0]),'decode negative binary32 bits')
    add('CO-float-ops-02',float(Fraction(3,2)+Fraction(1,4)),'exact rational addition')
    rounded=round(Fraction(11,8)*4)
    add('CO-float-ops-04',f'{rounded//4}.{rounded%4:02b}₂','nearest even on representable quarter increments')
    add('CO-hierarchy-02',f'{2+Fraction(4,100)*50}ns','hit latency plus miss probability times extra penalty')
    add('CO-capacity-01',f'{8//(16//8)*2}K字','parallel chips for word width, remaining groups for depth')
    add('CO-capacity-02',f'{(64*1024-1).bit_length()}根','byte address bits')
    add('CO-interleave-01',f'{14%4}号体','low-order interleave modulo')
    add('CO-disk-01',f'{60/6000/2*1000:g}ms','half a revolution')
    add('CO-disk-02',f'{8+4+1}ms','sum serial access components')
    add('CO-cache-map-01',f'{32-int(math.log2(32))-int(math.log2(4096//32))}位','address bits minus offset and direct-map index')
    add('CO-cache-map-02',f'{19%8}号行','block-to-line modulo')
    add('CO-cache-policy-01',replace_trace('ABAC',2,True)[-1],'LRU simulation')
    add('CO-virtual-01',hex(0x12345%4096),'page offset remainder')
    add('CO-virtual-04',4000+520,'segment base plus validated in-bounds offset')
    add('CO-instruction-01',f'{2**(16-6)}种','remaining address encodings')
    add('CO-addressing-01',1000+24,'base displacement sum')
    memory={200:500,500:17}
    add('CO-addressing-02',memory[memory[200]],'two-step indirect load')
    add('CO-endian-01',f'0x{int.from_bytes(bytes.fromhex("EF CD AB 89"),"little"):08X}','little-endian reconstruction')
    add('CO-endian-02',hex((0x12345678).to_bytes(4,'big')[1]),'big-endian byte extraction')
    add('CO-calls-03',1000-3*4,'predecrement stack')
    add('CO-cycle-02',sum([2,1,3]),'serial cycle sum')
    add('CO-pipeline-01',5+10-1,'pipeline filling plus remaining completions')
    add('CO-pipeline-03',f'{max([2,3,5])+1}ns','critical stage plus latch overhead')
    add('CO-bus-01',f'{32/8*100e6/1e6:g}MB/s','bytes per cycle times cycles per second')
    add('CO-bus-timing-02',2+4,'one address phase plus four data cycles')
    add('CO-polling-02',f'{20/1000*100:g}%','poll duration / poll interval')
    add('CO-interrupt-io-03',f'{2000*5e-6*100:g}%','interrupt service fraction')
    ratios={'甲':Fraction(12,4),'乙':Fraction(10,5)}
    winner=min(ratios,key=ratios.get)
    add('OS-schedule-metrics-01',f'{winner}更优，其带权周转为{ratios[winner]}','compare normalized turnaround')
    add('OS-schedule-metrics-02',8-5,'first scheduled minus arrival')
    add('OS-schedule-algorithms-01','、'.join(sorted({'A':5,'B':2,'C':1},key={'A':5,'B':2,'C':1}.get)),'nonpreemptive SJF ordering')
    add('OS-schedule-algorithms-02',rr_completion([('A',3),('B',3)],2)['B'],'round-robin queue simulation')
    response={'A':Fraction(6+3,3),'B':Fraction(8+8,8)}
    winner=max(response,key=response.get)
    add('OS-schedule-algorithms-04',f'{winner}，响应比为{response[winner]}','HRRN ratio calculation')
    add('OS-context-02',f'{5e-6*4000*100:g}%','context switch time fraction')
    add('OS-semaphore-01',min(5,3),'available permits versus five acquisitions without release')
    add('OS-classic-sync-01',f'{5-0}和{0}','empty slots and products')
    order=safe_order(1,{'P1':1,'P2':1},{'P1':2,'P2':3})
    add('OS-deadlock-02',f'存在，先{order[0]}后{order[1]}','single-resource banker safety simulation')
    add('OS-allocation-01',('合法，'+str(2000+499)) if 0<=499<500 else '非法','bounds check and base translation')
    add('OS-allocation-02',f'{next(n for n in [100,500,200] if n>=180)}大小的块','first-fit scan')
    add('OS-paging-01','和'.join(map(str,divmod(10300,4096))),'page quotient and offset remainder')
    add('OS-paging-02',f'{2**32//4096*4//2**20}MiB','page count times PTE size')
    add('OS-segmentation-02','越界，应拒绝或产生保护异常' if not 0<=120<120 else '合法，物理地址920','exclusive segment bound')
    add('OS-frames-03',f'{12//3}和{12*2//3}','proportional frame allocation')
    add('OS-replacement-01',replace_trace([1,2,3,1,4],3)[-1],'FIFO replacement simulation')
    add('OS-replacement-02',replace_trace([1,2,3,1,4],3,True)[-1],'LRU replacement simulation')
    pages=list('ABC'); bits=[1,0,1]; cursor=0
    while bits[cursor]:
        bits[cursor]=0
        cursor=(cursor+1)%len(bits)
    add('OS-replacement-04',pages[cursor],'Clock second-chance scan')
    add('OS-working-set-03',f'{80+2e-6*5e6:g} ns','baseline plus expected additional fault cost')
    add('OS-files-02',10+20,'advance open-file offset')
    add('OS-inode-02',4096//4,'pointers per indirect block')
    add('OS-file-layout-02',math.ceil(10/4),'round up allocated data blocks')
    add('OS-free-space-01',8192//8,'one bitmap bit per block')
    add('OS-buffer-02',f'{20/(12-8):g}秒','buffer capacity divided by net accumulation')
    head=50; pending=[10,55,58]; order=[]
    while pending:
        head=min(pending,key=lambda x:abs(x-head))
        pending.remove(head)
        order.append(head)
    add('OS-disk-schedule-01','、'.join(map(str,order)),'SSTF request selection')
    positions=[50,10,55,58]
    add('OS-disk-schedule-02',sum(abs(b-a) for a,b in zip(positions,positions[1:])),'FCFS head movements')
    positions=[50,55,80,199,10]
    add('OS-disk-schedule-05',sum(abs(b-a) for a,b in zip(positions,positions[1:])),'SCAN goes to endpoint before reversal')
    add('CN-performance-01',f'{12000/6e6*1000:g} ms','serialization delay')
    add('CN-performance-02',f'{(300-100)*1000/2e8*1000:g} ms','extra propagation distance divided by signal speed')
    add('CN-performance-03',f'{min([10,4,8])} Mbit/s','bottleneck upper bound')
    add('CN-layers-03',f'{900+20+20} B','two encapsulation headers')
    add('CN-signals-01',f'{2400*int(math.log2(16))} bit/s','symbols per second times bits per symbol')
    add('CN-capacity-01',f'{2**math.ceil(16000/(2*2000))}种','solve Nyquist bound for alphabet size')
    add('CN-capacity-02',f'{math.log2(1+31):g} Mbit/s','Shannon with linear signal-noise ratio')
    add('CN-encoding-04',f'{8000*math.log2(256)/1000:g} kbit/s','PCM sample rate times bits per sample')
    add('CN-switching-02',f'{1000*8/1e6*2*1000:g} ms','two full store-and-forward serializations')
    add('CN-framing-02',bit_stuff('111110'),'five-one bit stuffing')
    add('CN-detect-01',str('1011001'.count('1')%2),'even parity bit')
    add('CN-detect-02',crc('1101','1011'),'polynomial modulo-two long division')
    add('CN-correct-01',(5-1)//2,'bounded-distance correction radius')
    add('CN-correct-02',sum(a!=b for a,b in zip('10101','11100')),'Hamming distance')
    add('CN-correct-03',next(r for r in range(1,10) if 2**r>=8+r+1),'single-error syndrome capacity')
    add('CN-stopwait-02',Fraction(1,1+4+4),'stop-wait serialization fraction')
    add('CN-gbn-01',2**3-1,'GBN sequence-space constraint')
    add('CN-gbn-02','、'.join(map(str,range(2,5))),'retransmit outstanding suffix from timed-out base')
    add('CN-sr-01',2**4//2,'equal SR window half sequence space')
    add('CN-multiplex-02',f'{4*8*8000/1000:g} kbit/s','TDM frame size times frame rate')
    add('CN-random-access-02',f'{10e6*2*20e-6:g} bit','collision detection needs round-trip propagation duration')
    add('CN-random-access-04',f'{math.exp(-1):.3f}','slotted ALOHA throughput at unit offered load')
    add('CN-ethernet-01',f'{len(bytes.fromhex("02 1A 3B 4C 5D 6E"))*8} bit','address representation bit count')
    routes=[('10.0.0.0/8','A'),('10.2.0.0/16','B'),('10.2.3.0/24','C'),('0.0.0.0/0','D')]
    matches=[(ipaddress.ip_network(network).prefixlen,out) for network,out in routes if ipaddress.ip_address('10.2.3.9') in ipaddress.ip_network(network)]
    add('CN-forwarding-02',max(matches)[1],'longest-prefix lookup')
    add('CN-routing-02',shortest_path([('A','B',2),('A','C',6),('B','C',1),('B','D',7),('C','D',3)],'A','D'),'Dijkstra-style independent graph search')
    add('CN-ipv4-01',f'{100-7*4} B','subtract IHL in 32-bit words from total length')
    payload=(1500-20)//8*8
    add('CN-ipv4-02',f'{payload} B，{payload//8}','fragment payload rounded to 8-byte units')
    add('CN-subnet-01',2**(32-27)-2,'conventional host capacity')
    add('CN-subnet-02',str(ipaddress.ip_interface('192.168.20.150/26').network.broadcast_address),'subnet broadcast with four equal /26 partitions')
    add('CN-ipv6-01',8*4*4//8,'hex groups to address bytes')
    # The option includes the unit, unlike the arithmetic integer above.
    cases[-1]['computed_answer']+=' B'
    add('CN-ipv6-03',str(ipaddress.ip_address('2001:0db8:0000:0000:0000:0000:0000:0001')),'IPv6 zero compression')
    add('CN-rip-02',4+1,'neighbor distance plus one hop')
    add('CN-ospf-03',sum([5,7,3]),'path metric sum')
    add('CN-udp-02',120+8,'UDP header plus data length')
    add('CN-tcp-stream-01',1000+300,'next expected byte sequence')
    add('CN-tcp-connect-01',701-1,'SYN consumes one sequence number')
    add('CN-tcp-window-01',f'{min(12000,8000)-3000} B','smaller flow/congestion window minus bytes in flight')
    add('CN-tcp-congestion-01',f'{1*2**3} MSS','three ideal slow-start doubling rounds')
    add('CN-tcp-congestion-02',f'{max(16//2,2)} MSS和1 MSS','classic Reno timeout threshold and loss window')
    return cases


def ds_calculations(bank):
    checks = []

    def check(qid, computed, method):
        if not qid.startswith("DS-"):
            qid = "KEW-DS-" + qid
        q = bank[qid]
        actual = q["options"][q["answer"]]
        if actual != str(computed):
            raise ValueError(f"{qid}: answer {actual!r} differs from computed {computed!r}")
        checks.append({"question_id": qid, "computed_answer": str(computed), "method": method, "status": "passed"})

    def sequence(values):
        return "、".join(map(str, values))

    def compact(values):
        return json.dumps(values, ensure_ascii=False, separators=(",", ":"))

    check("adt-02", "{" + ",".join(map(str, sorted({2, 7} - {5}))) + "}", "set difference")
    check("seqlist-01", len(list(range(2, 7))), "enumerate shifted positions")
    check("seqlist-02", 200 + 5 * 12, "byte offset")
    check("list-applications-01", "(" + ",".join(map(str, sorted({1, 4, 8} | {2, 4, 9}))) + ")", "set union")
    check("list-applications-03", len(set([2, 2, 2, 5, 5, 8])), "distinct values")
    stack, popped = [], []
    for value in [6, 1, None, 8, None]:
        if value is None:
            popped.append(stack.pop())
        else:
            stack.append(value)
    check("stack-01", "，".join(map(str, popped)), "stack simulation")

    def stack_orders(rest, stack, output):
        if not rest and not stack:
            return {tuple(output)}
        results = set()
        if rest:
            results |= stack_orders(rest[1:], stack + [rest[0]], output)
        if stack:
            results |= stack_orders(rest, stack[:-1], output + [stack[-1]])
        return results

    possible = stack_orders([1, 2, 3], [], [])
    q = bank["KEW-DS-stack-03"]
    invalid = [v for v in q["options"].values() if tuple(map(int, v.split("，"))) not in possible]
    if len(invalid) != 1:
        raise ValueError("Stack question is not single answer")
    check("stack-03", invalid[0], "enumerate all legal stack orders")
    check("queue-01", (2 - 6 + 8) % 8, "circular queue count")
    full_rears = [r for r in range(6) if (r + 1) % 6 == 2]
    check("queue-02", full_rears[0], "enumerate full-state rear positions")
    depth = peak = 0
    for ch in "(()())":
        depth += 1 if ch == "(" else -1
        peak = max(peak, depth)
    check("stack-applications-01", peak, "bracket depth simulation")

    def postfix(expression):
        out, operators = [], []
        priority = {"+": 1, "-": 1, "*": 2, "/": 2}
        for ch in expression:
            if ch.isalpha():
                out.append(ch)
            elif ch == "(":
                operators.append(ch)
            elif ch == ")":
                while operators[-1] != "(":
                    out.append(operators.pop())
                operators.pop()
            else:
                while operators and operators[-1] != "(" and priority[operators[-1]] >= priority[ch]:
                    out.append(operators.pop())
                operators.append(ch)
        return "".join(out + operators[::-1])

    check("stack-applications-02", postfix("(a-b)*c+d"), "shunting-yard conversion")
    check("DS-2024-02", postfix("x+y*(z-u)/v"), "shunting-yard conversion")
    check("array-address-01", 1000 + (2 * 5 + 3) * 4, "row-major offset")
    check("array-address-02", 200 + ((3 - 1) * 3 + (2 - 1)) * 2, "column-major offset")
    check("array-address-03", "1和" + str(3), "compare row/column strides")
    lower = [(i, j) for i in range(1, 6) for j in range(1, i + 1)]
    check("matrix-storage-01", lower.index((4, 2)), "enumerate lower-triangle storage")
    check("matrix-storage-02", 6*6-sum(range(1, 7)), "full matrix minus stored triangular cells")
    check("matrix-storage-03", sum(abs(i - j) <= 1 for i in range(6) for j in range(6)), "enumerate tridiagonal cells")
    upper_by_column = [(i, j) for j in range(1, 11) for i in range(1, j + 1)]
    check("DS-2020-01", upper_by_column.index((2, 7)), "enumerate upper triangle by column with symmetry")
    check("tree-01", 18 - 1, "tree edge count")
    check("tree-02", (4 * 2 + 3) - (4 + 3) + 1, "degree sum identity")
    check("tree-03", f"第{4+1}层", "edge depth plus one")
    check("binary-01", (17-4+1)//2, "solve binary degree and node-count identities")
    check("binary-02", sum(2 ** i for i in range(4)), "sum of layer capacities")
    one_child = [i for i in range(1, 11) if 2 * i <= 10 < 2 * i + 1]
    check("binary-03", f"{one_child[0]}号结点", "enumerate complete-tree child indices")
    check("binary-storage-01", 13 // 2, "array parent index")
    position = 1
    for _ in range(4):
        position = 2 * position + 1
    check("binary-storage-03", position, "simulate right-child indices")
    tree = {"A": ("B", "C"), "B": ("D", None), "C": (None, "E"), "D": (None, None), "E": (None, None)}

    def walk(root, kind, tree):
        if root is None:
            return []
        left, right = tree[root]
        lvalues, rvalues = walk(left, kind, tree), walk(right, kind, tree)
        return [root] + lvalues + rvalues if kind == "pre" else lvalues + rvalues + [root]

    check("traversal-01", sequence(walk("A", "pre", tree)), "recursive traversal")

    ino, post = list("DGBEACF"), list("GDEBFCA")
    check("traversal-02", ino.index(post[-1]), "locate postorder root in inorder")
    parent, node, ancestors = [-1, 0, 0, 1, 1], 4, []
    while parent[node] != -1:
        node = parent[node]
        ancestors.append(node)
    check("tree-storage-01", sequence(ancestors), "follow parent array")
    multi = {"A": ["B", "C"], "B": ["D"], "C": [], "D": []}

    def multi_walk(node, post=False):
        children = sum((multi_walk(child, post) for child in multi[node]), [])
        return children + [node] if post else [node] + children

    check("forest-traversal-01", sequence(multi_walk("A")), "ordered tree preorder")
    check("forest-traversal-02", sequence(multi_walk("A", True)), "ordered tree postorder")
    q = bank["KEW-DS-huffman-01"]
    valid = []
    for option in q["options"].values():
        codes = option.split("、")
        if all(not b.startswith(a) for i, a in enumerate(codes) for j, b in enumerate(codes) if i != j):
            valid.append(option)
    if len(valid) != 1:
        raise ValueError("Prefix code question is not single answer")
    check("huffman-01", valid[0], "test all pairwise codeword prefixes")

    def wpl(weights):
        values = weights[:]
        heapq.heapify(values)
        total = 0
        while len(values) > 1:
            merged = heapq.heappop(values) + heapq.heappop(values)
            total += merged
            heapq.heappush(values, merged)
        return total

    check("DS-2019-03", (115 + 1) // 2, "full binary tree count")
    check("DS-2021-05", wpl([10, 12, 16, 21, 30]), "priority-queue Huffman construction")
    check("DS-2023-04", wpl([3, 4, 5, 6, 8, 10]) / 36, "Huffman WPL divided by frequency")
    values = [None, 9, 7, 8, 2, 3, 10]
    i = len(values) - 1
    while i > 1 and values[i] > values[i//2]:
        values[i], values[i//2] = values[i//2], values[i]
        i //= 2
    check("heap-01", compact(values[1:]), "max-heap sift up")

    def remove_max(values):
        maximum = values[0]
        last = values.pop()
        if values:
            values[0] = last
            i = 0
            while 2*i+1 < len(values):
                child = 2*i+1
                if child+1 < len(values) and values[child+1] > values[child]:
                    child += 1
                if values[i] >= values[child]:
                    break
                values[i], values[child] = values[child], values[i]
                i = child
        return values, maximum

    check("heap-02", compact(remove_max([9, 7, 8, 2, 3])[0]), "max-heap removal")
    check("graph-01", 2*7, "handshake identity")
    check("graph-02", 9, "each directed edge contributes one indegree")
    check("adj-matrix-01", 2*2, "symmetric matrix entries per edge")
    check("adj-list-01", 2*8, "undirected adjacency incidence count")

    def adjacency(edges):
        adj = {}
        for a, b in edges:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        return {k: sorted(v) for k, v in adj.items()}

    adj = adjacency([(1, 2), (1, 3), (2, 4), (3, 4)])
    visited = []

    def dfs(node):
        visited.append(node)
        for nxt in adj[node]:
            if nxt not in visited:
                dfs(nxt)

    dfs(1)
    check("dfs-01", sequence(visited), "DFS with sorted neighbors")

    def bfs(start, adj):
        distances, out, queue = {start: 0}, [], deque([start])
        while queue:
            node = queue.popleft()
            out.append(node)
            for nxt in adj[node]:
                if nxt not in distances:
                    distances[nxt] = distances[node] + 1
                    queue.append(nxt)
        return out, distances

    check("bfs-01", sequence(bfs(1, adjacency([(1, 2), (1, 3), (2, 4), (3, 5)]))[0]), "BFS simulation")
    check("bfs-02", bfs("a", adjacency([("a", "b"), ("b", "c"), ("a", "d"), ("d", "e"), ("e", "c")]))[1]["c"], "unweighted distance")
    edges = [("A", "B", 1), ("A", "C", 4), ("B", "C", 2), ("B", "D", 5), ("C", "D", 3)]
    totals = []
    for chosen in itertools.combinations(edges, 3):
        adj = adjacency([(a, b) for a, b, _ in chosen])
        if "A" in adj and len(bfs("A", adj)[0]) == 4:
            totals.append(sum(w for _, _, w in chosen))
    check("mst-01", min(totals), "enumerate all spanning trees")
    edges = [("s", "a", 2), ("s", "b", 7), ("a", "b", 3), ("b", "t", 1), ("a", "t", 8)]
    distance = {v: float("inf") for v in "sabt"}
    distance["s"] = 0
    for _ in range(3):
        for a, b, weight in edges:
            distance[b] = min(distance[b], distance[a] + weight)
    check("shortest-01", distance["t"], "Bellman-Ford relaxation")
    valid = []
    for option in bank["KEW-DS-topological-01"]["options"].values():
        position = {v: i for i, v in enumerate(option.split("、"))}
        if all(position[a] < position[b] for a, b in [("A", "C"), ("B", "C"), ("C", "D")]):
            valid.append(option)
    if len(valid) != 1:
        raise ValueError("Topological ordering question is not single answer")
    check("topological-01", valid[0], "validate precedence for every option")
    duration = max(3+4, 2+6)
    check("critical-01", duration, "enumerate AOE source-sink path lengths")
    check("critical-02", (duration-4)-3, "latest start minus earliest start")
    check("search-basics-01", sum(p*c for p, c in zip([Fraction(1, 2), Fraction(1, 3), Fraction(1, 6)], [1, 2, 3])), "weighted exact rational average")
    check("sequential-search-01", sum(range(1, 8))//7, "enumerate successful search positions")
    comparisons = 0
    for v in [3, 8, 12, 17, 25]:
        comparisons += 1
        if v >= 10:
            break
    check("sequential-search-02", comparisons, "ordered sequential scan")
    check("block-search-03", int(sum((block+1)+(pos+1) for block in range(3) for pos in range(3))/9), "enumerate all nine successful searches")
    values, low, high, trace = [2, 5, 9, 14, 20, 27, 35], 0, 6, []
    while low <= high:
        mid = (low+high)//2
        trace.append(values[mid])
        if values[mid] == 27:
            break
        if values[mid] < 27:
            low = mid+1
        else:
            high = mid-1
    check("binary-search-01", sequence(trace), "binary search simulation")
    check("b-tree-01", (5+1)//2-1, "minimum nonroot B-tree occupancy")
    check("b-tree-02", [10, 20, 30, 40, 50][2], "split median")
    counts = []
    for second_level_nodes in [2, 3]:
        for keys in itertools.product([1, 2], repeat=second_level_nodes):
            if sum(keys) == 4:
                counts.append(1+second_level_nodes+sum(k+1 for k in keys))
    check("DS-2021-09", max(counts), "enumerate feasible second-layer B-tree occupancies")
    check("hash-01", 9/12, "load ratio")
    slots, positions = [None]*7, []
    for key in [10, 17, 24]:
        pos = key % 7
        while slots[pos] is not None:
            pos = (pos+1) % 7
        slots[pos] = key
        positions.append(pos)
    check("hash-02", sequence(positions), "linear probing insertion")
    text, pattern = "ababa", "aba"
    matches = [i for i in range(len(text)-len(pattern)+1) if text[i:i+len(pattern)] == pattern]
    check("naive-match-01", "和".join(map(str, matches)), "enumerate substring matches")
    text, pattern, comparisons = "aaaaab", "aab", 0
    for start in range(len(text)-len(pattern)+1):
        success = True
        for j, ch in enumerate(pattern):
            comparisons += 1
            if text[start+j] != ch:
                success = False
                break
        if success:
            break
    check("naive-match-02", comparisons, "naive matcher with comparison counter")
    pattern = "ababaca"
    pi = [max([0] + [size for size in range(1, i+1) if pattern[:size] == pattern[i-size+1:i+1]]) for i in range(len(pattern))]
    check("kmp-01", compact(pi), "brute-force longest proper border, independent of KMP")
    check("kmp-02", pi[4], "border-length fallback")

    values = [5, 2, 4, 1]
    for i in range(1, 3):
        value, j = values[i], i-1
        while j >= 0 and values[j] > value:
            values[j+1] = values[j]
            j -= 1
        values[j+1] = value
    check("insertion-01", compact(values), "two insertion-sort passes")
    check("binary-insertion-02", str(sum(x <= 4 for x in [2, 4, 4, 7])) + "，即已有两个4之后", "stable upper-bound insertion position")
    values = [4, 1, 3, 2]
    for i in range(len(values)-1):
        if values[i] > values[i+1]:
            values[i], values[i+1] = values[i+1], values[i]
    check("bubble-01", compact(values), "one left-to-right bubble pass")
    values = [6, 3, 5, 1]
    index = values.index(min(values))
    values[0], values[index] = values[index], values[0]
    check("selection-01", compact(values), "first selection-sort pass")
    values = [8, 7, 6, 5, 4, 3]
    for offset in range(3):
        values[offset::3] = sorted(values[offset::3])
    check("shell-01", compact(values), "sort each gap-three subsequence")
    values, boundary = [4, 2, 5, 1, 3], 0
    pivot = values[-1]
    for i in range(len(values)-1):
        if values[i] <= pivot:
            values[i], values[boundary] = values[boundary], values[i]
            boundary += 1
    values[boundary], values[-1] = values[-1], values[boundary]
    check("quick-03", compact(values), "Lomuto partition simulation")
    rest, maximum = remove_max([10, 7, 9, 1, 3])
    check("heap-sort-02", compact(rest + [maximum]), "heap-sort extraction and adjustment")
    check("merge-sort-01", sequence(sorted([1, 6, 8] + [2, 4, 9])[:4]), "independent sorted merge result")
    count, rounds = 8, 0
    while count > 1:
        count = (count+1)//2
        rounds += 1
    check("merge-sort-03", rounds, "count pairwise merge rounds")
    check("radix-01", compact(sorted([42, 15, 31, 24, 12], key=lambda n: n%10)), "stable digit-key sort")
    old = sorted([93, 946, 372, 9, 146, 151, 301, 485, 236, 327, 43, 892], key=lambda n: n%10)
    index = old.index(372)
    check("DS-2021-10", f"{old[index-1]},{old[index+1]}", "stable units-digit order and neighboring records")
    runs, rounds = 16, 0
    while runs > 1:
        runs = (runs+3)//4
        rounds += 1
    check("external-01", rounds, "count four-way merge rounds")
    check("external-02", 100*2*(1+2), "block reads and writes across stages")
    active, frozen, incoming, out = [4, 7], [], iter([2, 9, 1]), []
    heapq.heapify(active)
    while active:
        current = heapq.heappop(active)
        out.append(current)
        try:
            value = next(incoming)
        except StopIteration:
            continue
        if value < current:
            frozen.append(value)
        else:
            heapq.heappush(active, value)
    check("replacement-01", compact(out), "replacement selection active/frozen simulation")
    costs = [a+b + (a+b+c) for a, b, c in itertools.permutations([2, 3, 9])]
    check("replacement-02", min(costs), "enumerate all two-stage merge choices")
    stack, output, incoming = [], [], iter("abcde")
    for action in [1, 1, 0, 1, 0, 1, 1, 0]:
        if action:
            stack.append(next(incoming))
        else:
            output.append(stack.pop())
    check("DS-2020-02", ",".join(output), "original stack trace simulation")
    return checks


def run():
    questions={}
    hashes={}
    for code,folder in FOLDERS.items():
        path=ROOT/folder/'questions.jsonl'
        hashes[code]=hashlib.sha256(path.read_bytes()).hexdigest()
        for line in path.read_text(encoding='utf-8').splitlines():
            q=json.loads(line)
            questions[q['id']]=q
    fixtures=json.loads((ROOT/'scripts/answer_cases.json').read_text(encoding='utf-8'))
    results=ds_calculations(questions)+calculations()
    if {r['question_id'] for r in results}!=set(fixtures) or len(results)!=len(fixtures):
        raise ValueError('Case fixtures are out of date or duplicated')
    # Validate all assumptions before comparing results; editing the question
    # requires a deliberate review of the fixed calculation inputs.
    for row in results:
        q=questions[row['question_id']]
        if binding(q)!=fixtures[q['id']]:
            raise ValueError(f'{q["id"]}: question changed; recheck calculation assumptions')
        answer=q['options'][q['answer']]
        if answer!=row['computed_answer']:
            raise ValueError(f'{q["id"]}: marked={answer}, calculated={row["computed_answer"]}')
        row['status']='passed'
    return dict(status='passed',checked_questions=len(results),total_questions=len(questions),
        per_subject={code:sum(questions[r['question_id']]['subject_code']==code for r in results) for code in FOLDERS},
        scope='独立计算和状态模拟；仅覆盖列出的题目，不代表全部定性答案及认知标签已经核验。',
        question_sha256=hashes,verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        fixture_sha256=hashlib.sha256((ROOT/'scripts/answer_cases.json').read_bytes()).hexdigest(),results=results)


if __name__=='__main__':
    report=run()
    print(json.dumps({k:report[k] for k in ('status','checked_questions','total_questions','per_subject')},ensure_ascii=False,indent=2))
