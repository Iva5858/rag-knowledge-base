#!/bin/bash
# Container entrypoint: clone vault on first boot, then run the bot.
set -e

VAULT_DIR="${VAULT_PATH:-/data/vault}"

# --- Vault setup (first boot only) ---
if [ ! -d "$VAULT_DIR/.git" ]; then
    if [ -n "$GIT_REMOTE" ]; then
        echo "[entrypoint] First boot — cloning vault from remote..."
        git clone "$GIT_REMOTE" "$VAULT_DIR"
        echo "[entrypoint] Vault cloned to $VAULT_DIR"
    else
        echo "[entrypoint] GIT_REMOTE not set — creating empty vault directory"
        mkdir -p "$VAULT_DIR"
    fi
else
    echo "[entrypoint] Vault already present at $VAULT_DIR"
fi

# --- Ensure ChromaDB directory exists ---
mkdir -p "${CHROMA_PATH:-/data/chroma}"

echo "[entrypoint] Starting bot..."
exec python bot/bot.py
