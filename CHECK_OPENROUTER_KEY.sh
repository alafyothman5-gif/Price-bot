#!/usr/bin/env bash
set -euo pipefail
APP_DIR="/opt/pricebot"
ENV_FILE="$APP_DIR/.env"

cd "$APP_DIR"

echo "=== CHECK PRICEBOT OPENROUTER CONFIG ==="
echo "Health:"
curl -m 8 -sS http://127.0.0.1:8090/health || true

echo ""
"$APP_DIR/venv/bin/python" - <<'PY'
import re, requests, sys
from pathlib import Path

env = Path('/opt/pricebot/.env')
text = env.read_text(encoding='utf-8', errors='ignore') if env.exists() else ''

def get(k):
    for line in text.splitlines():
        if line.strip().startswith(k + '='):
            return line.split('=', 1)[1].strip().strip('"').strip("'")
    return ''

order = get('AI_PROVIDER_ORDER')
model = get('AI_OPENROUTER_MODEL') or 'google/gemini-2.0-flash-001'
key = get('AI_OPENROUTER_KEYS')
print('AI_PROVIDER_ORDER:', order or 'NOT FOUND')
print('AI_OPENROUTER_MODEL:', model or 'NOT FOUND')
print('OpenRouter key saved:', 'YES' if key.startswith('sk-or-v1-') else 'NO')
if key.startswith('sk-or-v1-'):
    print('OpenRouter key masked:', key[:12] + '...' + key[-6:])
else:
    sys.exit(1)

headers = {
    'Authorization': 'Bearer ' + key,
    'Content-Type': 'application/json',
    'HTTP-Referer': 'https://46.101.148.246.sslip.io',
    'X-Title': 'PriceBot',
}
payload = {
    'model': model,
    'messages': [{'role': 'user', 'content': 'Reply with exactly: OK'}],
    'temperature': 0,
    'max_tokens': 10,
}
r = requests.post('https://openrouter.ai/api/v1/chat/completions', headers=headers, json=payload, timeout=30)
print('HTTP status:', r.status_code)
if r.status_code == 200:
    msg = r.json().get('choices', [{}])[0].get('message', {}).get('content', '').strip()
    print('Model reply:', msg)
    print('RESULT: OPENROUTER_WORKING')
else:
    print('Response:', r.text[:1000])
    print('RESULT: OPENROUTER_FAILED')
    sys.exit(1)
PY

echo "DONE"
