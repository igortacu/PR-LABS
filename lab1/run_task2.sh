#!/usr/bin/env bash
# Task 2: files on a USB drive. Usage: ./run_task2.sh /Volumes/YOUR_USB
# Copy data/parts/numbers_{1..8}.txt to the drive first. Before EVERY run the
# script asks you to eject, unplug and re-plug the drive so no data is cached.
# On macOS also disable Spotlight for the drive:  sudo mdutil -i off /Volumes/NAME
set -euo pipefail
cd "$(dirname "$0")"
make -s
USB="${1:?usage: $0 /Volumes/USB_NAME}"
NAME=$(basename "$USB")
mkdir -p results
: > results/raw_2_usb.txt
for t in 1 2 4; do
  echo ">>> Eject '$NAME', unplug it, plug it back in, wait until it is mounted, then press Enter (threads=$t)"
  diskutil unmount "$USB" >/dev/null 2>&1 || true
  read -r _
  until [ -d "$USB" ]; do sleep 1; done
  ./lab1 2 "$USB" $t | tee -a results/raw_2_usb.txt
done
