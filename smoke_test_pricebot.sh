#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"
python -m compileall -q .
python -m pytest -q
python acceptance_tests_v3.py
python acceptance_tests_v4.py
python acceptance_tests_final_v17.py
python acceptance_tests_final_v17_1.py
python acceptance_tests_final_v17_2.py
python acceptance_tests_final_v17_4.py
python acceptance_tests_final_v17_5.py
python acceptance_tests_final_v18.py
python acceptance_tests_final_v19.py
python acceptance_tests_final_v19_1.py
curl -fsS http://127.0.0.1:8000/health
echo

echo "PRICEBOT_SMOKE_TEST_OK"
