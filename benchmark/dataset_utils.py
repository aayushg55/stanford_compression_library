#!/usr/bin/env python3
"""Simple dataset utilities for benchmark script

For file-based benchmarks, treat everything as byte streams (0-255) for consistency.
This keeps evaluation fair across file types and implementation simple.
"""

import os
import glob
from typing import List
from scl.core.data_block import DataBlock
from scl.core.prob_dist import Frequencies
from scl.core.data_stream import Uint8FileDataStream


def read_file_as_bytes(file_path: str) -> DataBlock:
    """Read entire file as bytes (0-255) into DataBlock

    Always uses Uint8FileDataStream to treat everything as byte stream.
    This keeps benchmarks fair and consistent across file types.

    Args:
        file_path: Path to file

    Returns:
        DataBlock with bytes (integers 0-255)
    """
    data_list = []
    with Uint8FileDataStream(file_path, "rb") as fds:
        while True:
            s = fds.get_symbol()
            if s is None:
                break
            data_list.append(s)
    return DataBlock(data_list)


def get_frequencies_from_datablock(data_block: DataBlock) -> Frequencies:
    """Compute frequencies from DataBlock using built-in get_counts method."""
    return Frequencies(data_block.get_counts())


def load_dataset_files(dataset_name: str, project_root: str) -> List[str]:
    """Load dataset files from unzipped directory

    Args:
        dataset_name: Name of dataset (directory name, should be unzipped)
        project_root: Root directory of the project

    Returns:
        List of file paths
    """
    # Datasets are in benchmark/datasets/ relative to project root
    dataset_path = os.path.join(project_root, "benchmark", "datasets", dataset_name)

    if not os.path.isdir(dataset_path):
        raise ValueError(
            f"Dataset directory not found: {dataset_name} (checked {dataset_path})"
        )

    # Get all files (skip directories)
    files = []
    for file_path in glob.glob(os.path.join(dataset_path, "**", "*"), recursive=True):
        if os.path.isfile(file_path):
            files.append(file_path)

    if not files:
        raise ValueError(f"No files found in dataset: {dataset_name}")

    # Sort for consistent ordering
    files.sort()

    print(f"Loading dataset: {dataset_name}")
    print(f"Found {len(files)} files in {dataset_path}")
    for file_path in files:
        print(f"  {os.path.relpath(file_path, dataset_path)}")

    return files
