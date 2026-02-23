#!/bin/bash

# omniclaw release build script

echo "🚀 Building OmniClaw for release..."

# 1. Clean previous builds
echo "🧹 Cleaning up previous builds..."
rm -rf dist/ build/ *.egg-info/ src/*.egg-info/

# 2. Build the package
echo "📦 Building distribution packages..."
# Using uv if available, or hatch directly
if command -v uv &> /dev/null; then
    uv run hatch build
else
    echo "⚠️ 'uv' not found, trying 'hatch' directly..."
    hatch build
fi

# 3. Check the distribution
echo "🔍 Checking distribution artifacts..."
if command -v uv &> /dev/null; then
    uv run twine check dist/*
else
    twine check dist/*
fi

echo "✅ Build complete!"
echo ""
echo "To publish to PyPI:"
echo "  twine upload dist/*"
echo ""
