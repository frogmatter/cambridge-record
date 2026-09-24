#!/usr/bin/env bash
# Run this once to set up the Python environment on your Mac.
# After this you never need to run it again.

echo "Setting up Cambridge Record pipeline..."

# Create a virtual environment (isolated Python for this project)
python3 -m venv venv
echo "✓ Virtual environment created"

# Activate it and install libraries
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "✓ Libraries installed: $(pip list --format=columns | grep -E 'requests|beautifulsoup4|python-dotenv|lxml' | awk '{print $1}' | tr '\n' ' ')"

# Copy the .env template if .env doesn't exist yet
if [ ! -f .env ]; then
    cp .env.template .env
    echo "✓ Created .env file — open it and fill in your credentials"
else
    echo "✓ .env already exists"
fi

echo ""
echo "Setup complete. Next steps:"
echo "  1. Open .env in a text editor and fill in your credentials"
echo "  2. Run: source venv/bin/activate"
echo "  3. Run: python find_show_id.py   (to find your Cablecast Show ID)"
echo "  4. Run: python test_api.py        (to confirm WordPress is connected)"
