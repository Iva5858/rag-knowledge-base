#!/bin/bash
# Container entrypoint: configure paths, clone vault on first boot, start bot.
set -e

# Ensure data paths are set — explicit export so child processes inherit them
export CHROMA_PATH="${CHROMA_PATH:-/data/chroma}"
export VAULT_PATH="${VAULT_PATH:-/data/vault}"

# Build GIT_REMOTE from GITHUB_PAT + GIT_REMOTE_REPO if not already set as a full URL.
# GITHUB_PAT is a Fly.io secret; GIT_REMOTE_REPO is a non-secret env var in fly.toml.
if [ -z "$GIT_REMOTE" ] && [ -n "$GITHUB_PAT" ] && [ -n "$GIT_REMOTE_REPO" ]; then
    export GIT_REMOTE="https://${GITHUB_PAT}@${GIT_REMOTE_REPO}"
    echo "[entrypoint] Built GIT_REMOTE from GITHUB_PAT + GIT_REMOTE_REPO"
fi

# --- Vault setup (first boot only) ---
if [ ! -d "$VAULT_PATH/.git" ]; then
    if [ -n "$GIT_REMOTE" ]; then
        echo "[entrypoint] First boot — cloning vault into $VAULT_PATH..."
        if git clone "$GIT_REMOTE" "$VAULT_PATH"; then
            echo "[entrypoint] Vault cloned successfully"
        else
            echo "[entrypoint] WARNING: git clone failed — bot will start without vault sync"
            mkdir -p "$VAULT_PATH"
        fi
    else
        echo "[entrypoint] GIT_REMOTE not set — creating empty vault directory"
        mkdir -p "$VAULT_PATH"
    fi
else
    echo "[entrypoint] Vault already present at $VAULT_PATH"
fi

# Ensure ChromaDB directory exists on the persistent volume
mkdir -p "$CHROMA_PATH"

echo "[entrypoint] VAULT_PATH=$VAULT_PATH  CHROMA_PATH=$CHROMA_PATH"
echo "[entrypoint] Starting bot..."
exec python bot/bot.py
