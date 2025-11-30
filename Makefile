# SPDX-License-Identifier: MIT
# Makefile for Stanford Compression Library

.PHONY: help install-linters lint format test clean
.PHONY: benchmark-fse datasets

DATASET_DIR := scl/benchmark/datasets

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install-linters: ## Install the linters (ruff, mypy)
	pip install uv mypy==1.9.0 ruff==0.6.9

# Your new files - edit my_files.txt to add/remove files
NEW_FILES := $(shell python3 get_my_files.py)

lint: ## Run all linting checks (only on your new files)
	@echo "Running ruff format check on your new files..."
	python -m ruff format --check $(NEW_FILES)
	@echo "Running ruff lint check on your new files..."
	python -m ruff check $(NEW_FILES)
	@echo "All linting checks passed!"

format: ## Format code with ruff (only your new files)
	@echo "Formatting your new files with ruff..."
	python -m ruff format $(NEW_FILES)
	@echo "Code formatting complete!"


test: ## Run all tests
	python -m pytest

# Benchmarking
benchmark-fse: ## Run FSE benchmarks against other codecs
	@echo "Running FSE benchmarks..."
	conda run -n ee274_env PYTHONPATH=. python scl/tests/benchmark_fse.py

datasets: ## Download and unpack benchmark corpora into scl/benchmark/datasets (Silesia, Canterbury, Calgary, Artificial, Large, Misc)
	@set -e; \
	mkdir -p $(DATASET_DIR); \
	download_unpack() { \
		URL="$$1"; DEST="$$2"; ZIPNAME="$$3"; \
		DESTDIR="$(DATASET_DIR)/$$DEST"; \
		mkdir -p "$$DESTDIR"; \
		if [ -n "$$(ls -A "$$DESTDIR" 2>/dev/null)" ]; then \
			echo "Skipping $$DEST (already populated)"; \
		else \
			ZIPFILE="$(DATASET_DIR)/$$ZIPNAME"; \
			echo "Fetching $$DEST from $$URL ..."; \
			curl -L "$$URL" -o "$$ZIPFILE"; \
			unzip -q "$$ZIPFILE" -d "$$DESTDIR"; \
		fi; \
	}; \
	download_unpack "https://sun.aei.polsl.pl/~sdeor/corpus/silesia.zip" "silesia" "silesia.zip"; \
	download_unpack "https://corpus.canterbury.ac.nz/resources/cantrbry.zip" "cantrbry" "cantrbry.zip"; \
	download_unpack "https://corpus.canterbury.ac.nz/resources/calgary.zip" "calgary" "calgary.zip"; \
	download_unpack "https://corpus.canterbury.ac.nz/resources/artificl.zip" "artificl" "artificl.zip"; \
	download_unpack "https://corpus.canterbury.ac.nz/resources/large.zip" "large" "large.zip"; \
	download_unpack "https://corpus.canterbury.ac.nz/resources/misc.zip" "misc" "misc.zip"; \
	echo "Done. Datasets unpacked under $(DATASET_DIR)."

clean: ## Clean up cache files
	find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -r {} + 2>/dev/null || true
	@echo "Cleanup complete!"
