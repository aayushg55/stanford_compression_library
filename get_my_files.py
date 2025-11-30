#!/usr/bin/env python3
"""Helper script to read my_files.txt and output file list for Makefile"""
import sys

try:
    with open('my_files.txt', 'r') as f:
        files = []
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                files.append(line)
        print(' '.join(files))
except FileNotFoundError:
    print('')
    sys.exit(0)

