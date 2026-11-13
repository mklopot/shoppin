"""
Local Verification Utility for Shoppin.
Executes Ruff linting, import formatting, and Pytest test suites.
Usage: python scripts/verify.py [--fast]
"""

import subprocess
import sys


def run_command(cmd: list[str], description: str) -> bool:
    print("\n====================================================================")
    print(f" ==> Running: {description} ({' '.join(cmd)})")
    print("====================================================================")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n❌ FAILED: {description} exited with code {result.returncode}")
        return False
    print(f"✅ PASSED: {description}")
    return True


def main() -> None:
    is_fast = "--fast" in sys.argv

    # 1. Ruff Lint & Format Check
    if not run_command([sys.executable, "-m", "ruff", "check", "."], "Ruff Linting"):
        sys.exit(1)

    # 2. Pytest Test Suite
    pytest_cmd = [sys.executable, "-m", "pytest", "-q"]
    if is_fast:
        # Run core tests only
        pytest_cmd.append("tests/test_recipes.py")

    if not run_command(pytest_cmd, "Pytest Test Suite" if not is_fast else "Fast Core Tests"):
        sys.exit(1)

    print("\n🎉 All verification checks passed cleanly!\n")


if __name__ == "__main__":
    main()
