"""Compatibility acceptance entrypoint for the removed v2 image/text fallback path.

Final production behavior is strict V4-only. Run acceptance_tests_final_v17.py
for launch validation.
"""
from acceptance_tests_final_v17 import main

if __name__ == "__main__":
    main()
