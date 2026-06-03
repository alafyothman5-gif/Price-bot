#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/pricebot"
ENV_FILE="$APP_DIR/.env"
MODEL_DEFAULT="google/gemini-2.0-flash-001"
TS="$(date +%Y%m%d_%H%M%S)"

if [ ! -d "$APP_DIR" ]; then
  echo "ERROR: /opt/pricebot غير موجود"
  exit 1
fi

mkdir -p "$APP_DIR/backups"
[ -f "$ENV_FILE" ] || touch "$ENV_FILE"
cp "$ENV_FILE" "$APP_DIR/backups/.env.before_openrouter_key_$TS.bak"
chmod 600 "$ENV_FILE"

printf 'الصق مفتاح OpenRouter الآن. لن يظهر على الشاشة.\n'
printf 'يجب أن يبدأ بـ sk-or-v1-\n'
read -r -s -p 'OpenRouter key: ' OR_KEY
printf '\n'
OR_KEY="$(printf '%s' "$OR_KEY" | tr -d '\r\n ' | sed 's/^Bearer[[:space:]]*//I')"

if [[ ! "$OR_KEY" == sk-or-v1-* ]]; then
  echo "ERROR: المفتاح لا يبدأ بـ sk-or-v1-"
  echo "لم يتم حفظ أي مفتاح."
  exit 1
fi

export OR_KEY MODEL_DEFAULT ENV_FILE
python3 - <<'PY'
import os
from pathlib import Path

env_path = Path(os.environ.get("ENV_FILE", "/opt/pricebot/.env"))
openrouter_key = os.environ["OR_KEY"].strip()
model = os.environ.get("MODEL_DEFAULT", "google/gemini-2.0-flash-001").strip()

values = {
    "AI_ENABLED": "yes",
    "AI_PROVIDER_ORDER": "openrouter",
    "AI_OPENROUTER_MODEL": model,
    "AI_OPENROUTER_KEYS": openrouter_key,
    "AI_GEMINI_KEYS": "",
    "AI_GROQ_KEYS": "",
    "AI_OPENAI_KEYS": "",
    "AI_CUSTOM_KEYS": "",
    "AI_API_KEY": "",
    "AI_PROVIDER": "openrouter",
    "AI_MODEL": model,
    "AI_OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1/chat/completions",
}

lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines() if env_path.exists() else []
seen = set()
out = []
for line in lines:
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        k = stripped.split("=", 1)[0].strip()
        if k in values:
            out.append(f"{k}={values[k]}")
            seen.add(k)
        else:
            out.append(line)
    else:
        out.append(line)
for k, v in values.items():
    if k not in seen:
        out.append(f"{k}={v}")

env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
os.chmod(env_path, 0o600)
PY

echo "تم حفظ المفتاح داخل /opt/pricebot/.env بدون طباعته."

echo "إعادة تشغيل البوت..."
systemctl restart pricebot
sleep 4

echo "Health:"
curl -m 8 -sS http://127.0.0.1:8090/health || true

echo ""
echo "اختبار OpenRouter من السيرفر..."
export OR_KEY MODEL_DEFAULT
"$APP_DIR/venv/bin/python" - <<'PY'
import os, sys, requests
key = os.environ.get("OR_KEY", "").strip()
model = os.environ.get("MODEL_DEFAULT", "google/gemini-2.0-flash-001")
headers = {
    "Authorization": "Bearer " + key,
    "Content-Type": "application/json",
    "HTTP-Referer": "https://46.101.148.246.sslip.io",
    "X-Title": "PriceBot",
}
payload = {
    "model": model,
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    "temperature": 0,
    "max_tokens": 10,
}
try:
    r = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
    print("HTTP status:", r.status_code)
    if r.status_code == 200:
        data = r.json()
        msg = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        print("Model reply:", msg)
        if "OK" in msg.upper():
            print("RESULT: OPENROUTER_WORKING")
            sys.exit(0)
    print("Response:", r.text[:1000])
    print("RESULT: OPENROUTER_FAILED")
    sys.exit(1)
except Exception as e:
    print("ERROR:", repr(e))
    print("RESULT: OPENROUTER_FAILED")
    sys.exit(1)
PY

echo "DONE"
