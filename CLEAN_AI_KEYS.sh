#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pricebot"
ENV_FILE="$APP_DIR/.env"
TS="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$APP_DIR/backups"
if [ -f "$ENV_FILE" ]; then
  cp "$ENV_FILE" "$APP_DIR/backups/.env.before_ai_clean_$TS.bak"
else
  touch "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

APP_DIR="$APP_DIR" ENV_FILE="$ENV_FILE" python3 - <<'PY'
import os
from pathlib import Path

env_path = Path(os.environ.get("ENV_FILE", "/opt/pricebot/.env"))
existing = env_path.read_text(encoding="utf-8", errors="ignore").splitlines() if env_path.exists() else []

# Remove any old AI-related keys to avoid confusion, including legacy names.
ai_keys = {
    "AI_ENABLED",
    "AI_PROVIDER_ORDER",
    "AI_OPENROUTER_MODEL",
    "AI_GEMINI_MODEL",
    "AI_GROQ_MODEL",
    "AI_OPENAI_MODEL",
    "AI_CUSTOM_MODEL",
    "AI_OPENROUTER_KEYS",
    "AI_GEMINI_KEYS",
    "AI_GROQ_KEYS",
    "AI_OPENAI_KEYS",
    "AI_CUSTOM_KEYS",
    "AI_API_KEY",
    "AI_PROVIDER",
    "AI_MODEL",
    "AI_BASE_URL",
    "AI_OPENROUTER_BASE_URL",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
}

out = []
for line in existing:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        k = stripped.split("=", 1)[0].strip()
        if k in ai_keys:
            continue
    out.append(line)

# Clean default state: AI enabled but no key yet. OpenRouter only.
out.extend([
    "",
    "# AI settings reset by CLEAN_AI_KEYS.sh",
    "AI_ENABLED=yes",
    "AI_PROVIDER_ORDER=openrouter",
    "AI_OPENROUTER_MODEL=google/gemini-2.5-flash-lite",
    "AI_GEMINI_MODEL=gemini-2.5-flash-lite",
    "AI_GROQ_MODEL=llama-3.1-8b-instant",
    "AI_OPENROUTER_KEYS=",
    "AI_GEMINI_KEYS=",
    "AI_GROQ_KEYS=",
    "AI_OPENAI_KEYS=",
    "AI_API_KEY=",
    "AI_PROVIDER=openrouter",
    "AI_MODEL=google/gemini-2.5-flash-lite",
    "AI_OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions",
])

env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
os.chmod(env_path, 0o600)
PY

echo "AI keys/settings cleaned. WhatsApp tokens/products/database were not touched."
