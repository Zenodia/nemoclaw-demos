#!/bin/bash
# Docker entrypoint for AgenticTA with Vault initialization

set -e

echo "🚀 Starting AgenticTA..."

# Initialize Vault token renewal if configured
if [ -n "$VAULT_ADDR" ] && [ -n "$VAULT_TOKEN" ]; then
    echo "✅ Vault configured: $VAULT_ADDR"
    echo "   Starting token auto-renewal..."
    
    # Import vault_init in a Python subprocess to initialize
    python3 -c "from vault import vault_init" 2>/dev/null || {
        echo "⚠️  Vault auto-renewal not available"
    }
else
    echo "ℹ️  Vault not configured - using .env fallback"
fi

# Execute the main command
exec "$@"

