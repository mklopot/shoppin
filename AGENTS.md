# Shoppin AI & Development Guidelines (AGENTS.md)

This document establishes the automated quality standards, testing policies, and continuous delivery rules for the Shoppin codebase.

---

## 1. Quality & Pre-Commit Standards

- **Strict Linting with Ruff**:
  - Always run `ruff check .` before committing any code changes.
  - Zero lint warnings allowed (`I001` unsorted imports, `F401` unused imports, `F841` unused local variables, etc.).
  - A Git pre-commit hook is installed at `.githooks/pre-commit` (configured via `git config core.hooksPath .githooks`) which automatically blocks any commit containing Ruff errors.
  - Fix any auto-correctable issues immediately with `ruff check . --fix`.

---

## 2. Testing & Cross-Module Regression Prevention

- **Targeted vs. Full Test Runs**:
  - **Component-Isolated Changes**: When modifying a single standalone view or template (e.g., recipe details layout), running targeted test suites (e.g. `pytest tests/test_recipes.py`) is acceptable during development.
  - **Shared Service Layer Changes**: Whenever editing services or models that span multiple applications:
    - `apps/mealplans/services/mealplan_service.py`
    - `apps/recipes/services/recipe_service.py`
    - `apps/shopping/services/broadcaster.py` or `store_service.py`
    - `apps/core/services/workspace_service.py`
    - Core database models or model `clean()` / permissions logic
    - **MANDATORY**: Run the full test suite (`pytest`) or verify all dependent consumer suites (`test_mealplans.py`, `test_immutable_link.py`, `test_websockets.py`, `test_presets.py`, `test_recipes.py`) before pushing.
  - Ensure all 276+ tests pass with zero failures.

---

## 3. Continuous Integration & Deployment (CI/CD)

- GitHub Actions pipeline is defined in `.github/workflows/deploy.yml`.
- On push to `v2-django` or `main`:
  1. **`test` job**: Installs `.[dev]`, runs `ruff check .`, and runs `pytest`.
  2. **`deploy` job**: On successful completion of `test`, SSHs into the production Lightsail server and runs:
     ```bash
     bash /app/deploy/lightsail/update.sh
     ```
  3. `update.sh` automatically pulls the latest commit, runs migrations, imports recipe additions, collects static files, reloads Caddy with zero downtime, restarts the Daphne ASGI service, and verifies the `/health/` probe.
