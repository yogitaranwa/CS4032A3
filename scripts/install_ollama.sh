#!/usr/bin/env bash
# Install Ollama (pinned) on a Linux runner, start it, pull phi3.5 and record what was pulled.
set -euo pipefail
OLLAMA_VERSION="${OLLAMA_VERSION:-0.5.7}"
curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION="$OLLAMA_VERSION" sh
if ! curl -fs http://localhost:11434/ >/dev/null 2>&1; then
  OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=24h nohup ollama serve > ollama.log 2>&1 &
fi
for _ in $(seq 1 60); do curl -fs http://localhost:11434/ >/dev/null 2>&1 && break; sleep 1; done
ollama pull phi3.5
mkdir -p out
{ ollama --version; ollama list; } | tee out/ollama_info.txt
