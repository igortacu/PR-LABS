#!/usr/bin/env bash
# Python (GIL) comparison runs -> results/py_raw_*.txt
set -euo pipefail
cd "$(dirname "$0")"
F=data/numbers.txt; THREADS="1 2 4 8 16 32 64"
: > results/py_raw_1a.txt; : > results/py_raw_1b.txt; : > results/py_raw_1c.txt; : > results/py_raw_2_local.txt
for t in $THREADS; do for r in 1 2 3; do python3 lab1.py 1a $F $t | tee -a results/py_raw_1a.txt; done; done
for v in unsync unsync unsync local local local mutex; do python3 lab1.py 1b $F $v 8 | tee -a results/py_raw_1b.txt; done
for t in $THREADS; do for r in 1 2; do python3 lab1.py 1c $F $t 10000 100 | tee -a results/py_raw_1c.txt; done; done
for t in 1 2 4; do python3 lab1.py 2 data/parts $t | tee -a results/py_raw_2_local.txt; done
echo done
