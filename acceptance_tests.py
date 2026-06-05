"""Compatibility acceptance entrypoint.

The legacy v1 tests covered old matcher/fast fallback behavior. Final launch
validation is now in acceptance_tests_final_v17.py.
"""
from acceptance_tests_final_v17 import main

if __name__ == "__main__":
    main()
