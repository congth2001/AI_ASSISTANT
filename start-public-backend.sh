#!/bin/bash

set -e

# Backend root directory
BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect Python virtual environment
if [ -f "$BACKEND_ROOT/env/bin/python" ]; then
    PYTHON_PATH="$BACKEND_ROOT/env/bin/python"
elif [ -f "$BACKEND_ROOT/.venv/bin/python" ]; then
    PYTHON_PATH="$BACKEND_ROOT/.venv/bin/python"
else
    echo "ERROR: Python virtual environment not found (env or .venv)"
    exit 1
fi

# Get frontend origin
FRONTEND_ORIGIN="$1"

if [ -z "$FRONTEND_ORIGIN" ]; then
    echo "Usage: $0 https://your-frontend-domain.com"
    exit 1
fi

if [[ ! "$FRONTEND_ORIGIN" =~ ^https:// ]]; then
    echo "ERROR: Frontend origin must start with https://"
    exit 1
fi

# Remove trailing slash
FRONTEND_ORIGIN="${FRONTEND_ORIGIN%/}"

# Configure environment variable
export PUBLIC_FRONTEND_ORIGINS="$FRONTEND_ORIGIN"

# Move to backend directory
cd "$BACKEND_ROOT"

echo "========================================"
echo "Starting FastAPI Backend"
echo "Backend: $BACKEND_ROOT"
echo "Python: $PYTHON_PATH"
echo "Frontend: $PUBLIC_FRONTEND_ORIGINS"
echo "========================================"

echo "Keep this terminal open while the frontend is in use."

# Start application
exec "$PYTHON_PATH" main.py