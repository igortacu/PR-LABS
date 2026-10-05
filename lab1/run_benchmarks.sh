#!/usr/bin/env bash
# Runs Tasks 1a, 1b, 1c (and the Q6 variants). Raw output goes to results/raw_*.txt.
set -euo pipefail
cd "$(dirname "$0")"
make -s
mkdir -p results
F=data/numbers.txt
THREADS="1 2 4 8 16 32 64"
CPUS=$(./lab1 cpus)

: > results/raw_1a.txt; : > results/raw_1b.txt; : > results/raw_1c.txt; : > results/raw_1c_q6.txt

echo "== Task 1a (5 runs per thread count)"
for t in $THREADS; do for r in 1 2 3 4 5; do ./lab1 1a $F $t | tee -a results/raw_1a.txt; done; done

echo "== Task 1b ($CPUS threads; unsync x3, mutex x3, local x3)"
for v in unsync unsync unsync mutex mutex mutex local local local; do ./lab1 1b $F $v $CPUS | tee -a results/raw_1b.txt; done

echo "== Task 1c (3 runs per worker count)"
for t in $THREADS; do for r in 1 2 3; do ./lab1 1c $F $t 10000 100 | tee -a results/raw_1c.txt; done; done

echo "== Task 1c, question 6 (workers=$CPUS)"
./lab1 1c $F $CPUS 10000 0 | tee -a results/raw_1c_q6.txt   # unbounded queue, normal batches
./lab1 1c $F $CPUS 1 100   | tee -a results/raw_1c_q6.txt   # batches of one line, bounded queue
./lab1 1c $F $CPUS 1 0     | tee -a results/raw_1c_q6.txt   # batches of one line, unbounded queue
echo done
