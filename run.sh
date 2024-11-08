#!/bin/bash

# PixelLlama info
echo "PixelLlama - version 0.92a"
echo "Launching PixelLlama..."

# Set the name of your virtual environment
VENV_NAME=".venv"

# Check if the virtual environment exists by looking for pyvenv.cfg
if [ ! -f "$VENV_NAME/bin/python" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_NAME"
fi

# Activate the virtual environment
source "$VENV_NAME/bin/activate"

# Check if required packages are installed by comparing installed versions
for i in PyQt6 PyQt6-WebEngine requests; do
    pip show "$i" > /dev/null 2>&1
    if [ $? -ne 0 ]; then
        need_install=1
    fi
done

# Check if requirements are installed
REQUIREMENTS_FILE="requirements.txt"

# Install or upgrade the required packages only if needed
if [ -n "$need_install" ]; then
    echo "Installing/Upgrading required packages..."
    pip install -r "$REQUIREMENTS_FILE"
fi

# Run the Python script using python
echo "Running PixelLlama..."
python main.py "$@"

# Deactivate the virtual environment
deactivate

# Exit the script
exit