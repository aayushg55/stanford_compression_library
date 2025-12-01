#!/bin/bash
# Script to run FSE tests with conda environment activation

# Activate conda environment
echo "Activating conda environment: ee274_env"
source $(conda info --base)/etc/profile.d/conda.sh
conda activate ee274_env

# Check if activation was successful
if [ $? -ne 0 ]; then
    echo "Error: Failed to activate conda environment 'ee274_env'"
    echo "Please ensure the environment exists: conda create -n ee274_env"
    exit 1
fi

echo "Running FSE tests..."
echo ""

# Run the FSE tests
python -c "from scl.compressors.fse import test_fse_basic, test_fse_coding; test_fse_basic(); test_fse_coding(); print('All FSE tests passed!')"

# Deactivate conda environment
conda deactivate

