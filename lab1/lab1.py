#!/usr/bin/env python3
"""Lab 1 in Python (threading, subject to the GIL). Same CLI/output as lab1.c.

  lab1.py 1a <file> <threads>
  lab1.py 1b <file> <unsync|mutex|local> [threads=logical CPUs]
  lab1.py 1c <file> <workers> [batch=10000] [qcap=100]
  lab1.py 2  <dir> <threads>
"""
import array, os, queue, resource, sys, threading, time
from itertools import islice

def peak_mb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return r / 1048576 if sys.platform == "darwin" else r / 1024

def report(task, variant, threads, ms, c, extra=""):
    print(f"RESULT task={task} variant={variant} threads={threads} time_ms={ms:.1f} "
          f"peak_mb={peak_mb():.1f} neg={c[0]} pos={c[1]} zero={c[2]} total={sum(c)} {extra}", flush=True)

def count_tokens(tokens, c):
    neg = pos = zero = 0
    for t in tokens:
        v = int(t)
        if v < 0: neg += 1
        elif v > 0: pos += 1
        else: zero += 1
    c[0] += neg; c[1] += pos; c[2] += zero

def boundary(fd, size, b):
    if b <= 0: return 0
    if b >= size: return size
    pos = b - 1
    while True:
        buf = os.pread(fd, 4096, pos)
        if not buf: return size
        i = buf.find(b"\n")
        if i >= 0: return pos + i + 1
        pos += len(buf)

def task_1a(path, T):
    fd = os.open(path, os.O_RDONLY)
    size = os.fstat(fd).st_size
    results = [[0, 0, 0] for _ in range(T)]
    def work(i):
        s = boundary(fd, size, size * i // T)
        e = boundary(fd, size, size * (i + 1) // T)
        carry, pos = b"", s
        while pos < e:
            chunk = os.pread(fd, min(1 << 20, e - pos), pos)
            if not chunk: break
            pos += len(chunk)
            data = carry + chunk
            k = data.rfind(b"\n") + 1 if pos < e else len(data)
            count_tokens(data[:k].split(), results[i])
            carry = data[k:]
        if carry: count_tokens(carry.split(), results[i])
    t0 = time.perf_counter()
    ths = [threading.Thread(target=work, args=(i,)) for i in range(T)]
    for t in ths: t.start()
    for t in ths: t.join()
    ms = (time.perf_counter() - t0) * 1e3
    report("1a", "split-file", T, ms, [sum(r[j] for r in results) for j in range(3)])

def task_1b(path, ver, T):
    arr = array.array("i")
    with open(path, "rb") as f:                      # loading is not measured
        for chunk in iter(lambda: f.readlines(1 << 24), []):
            arr.extend(map(int, chunk))
    n = len(arr)
    shared = [0, 0, 0]
    lock = threading.Lock()
    local = [[0, 0, 0] for _ in range(T)]
    def work(i):
        s, e = n * i // T, n * (i + 1) // T
        if ver == "unsync":
            for k in range(s, e):
                v = arr[k]
                shared[0 if v < 0 else 1 if v > 0 else 2] += 1
        elif ver == "mutex":
            for k in range(s, e):
                v = arr[k]
                with lock:
                    shared[0 if v < 0 else 1 if v > 0 else 2] += 1
        else:
            c = local[i]
            for k in range(s, e):
                v = arr[k]
                c[0 if v < 0 else 1 if v > 0 else 2] += 1
    t0 = time.perf_counter()
    ths = [threading.Thread(target=work, args=(i,)) for i in range(T)]
    for t in ths: t.start()
    for t in ths: t.join()
    ms = (time.perf_counter() - t0) * 1e3
    c = [sum(r[j] for r in local) for j in range(3)] if ver == "local" else shared
    report("1b", ver, T, ms, c)

def task_1c(path, W, batch, qcap):
    q = queue.Queue(maxsize=qcap)
    results = [[0, 0, 0] for _ in range(W)]
    def worker(i):
        while True:
            b = q.get()
            if b is None: return
            count_tokens(b, results[i])
    t0 = time.perf_counter()
    ths = [threading.Thread(target=worker, args=(i,)) for i in range(W)]
    for t in ths: t.start()
    maxq = lines = 0
    with open(path, "rb") as f:
        while True:
            b = list(islice(f, batch))
            if not b: break
            lines += len(b)
            q.put(b)
            maxq = max(maxq, q.qsize())
    for _ in range(W): q.put(None)
    for t in ths: t.join()
    ms = (time.perf_counter() - t0) * 1e3
    report("1c", "producer-consumer", W, ms, [sum(r[j] for r in results) for j in range(3)],
           f"batch={batch} qcap={qcap} maxq={maxq} read_lines={lines}")

def task_2(d, T):
    results = [[0, 0, 0] for _ in range(T)]
    def work(i):
        for k in range(i, 8, T):
            with open(f"{d}/numbers_{k + 1}.txt", "rb") as f:
                data = f.read()                       # one read into one buffer
            count_tokens(data.split(), results[i])
    t0 = time.perf_counter()
    ths = [threading.Thread(target=work, args=(i,)) for i in range(T)]
    for t in ths: t.start()
    for t in ths: t.join()
    ms = (time.perf_counter() - t0) * 1e3
    report("2", "files", T, ms, [sum(r[j] for r in results) for j in range(3)])

if __name__ == "__main__":
    a = sys.argv
    if a[1] == "1a": task_1a(a[2], int(a[3]))
    elif a[1] == "1b": task_1b(a[2], a[3], int(a[4]) if len(a) > 4 else os.cpu_count())
    elif a[1] == "1c": task_1c(a[2], int(a[3]), int(a[4]) if len(a) > 4 else 10000, int(a[5]) if len(a) > 5 else 100)
    elif a[1] == "2": task_2(a[2], int(a[3]))
    else: sys.exit(__doc__)
