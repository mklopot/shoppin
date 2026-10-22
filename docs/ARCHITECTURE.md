# Shoppin Architecture & Developer Guide

Welcome to the **Shoppin** codebase! This guide is written to help you quickly understand how the system is structured, how data flows through the application, and the design patterns used across the stack.

---

## 1. High-Level Technology Stack

* **Backend:** Python 3.12+ with **Django 6** (asynchronous & synchronous capabilities).
* **Real-Time Communication:** **Django Channels** and **Daphne** ASGI server for WebSockets.
* **Frontend Interactivity:** **HTMX 2.0** + **SortableJS** (no heavyweight single-page app framework needed).
* **Styling:** **Tailwind CSS** configured with semantic themes and custom color palettes.
* **Database:** SQLite in development / PostgreSQL-ready.
* **Testing & Quality:** **Pytest** (`pytest-django`) and **Ruff** for high-speed linting.

---

## 2. Core Mental Model: The HTMX Partial Lifecycle

Instead of building a separate Single Page Application (SPA) in React or Vue with complex JSON API serializers and duplicated client-side state, Shoppin uses **server-driven HTML partials**:

```
[ User Interaction ]  -->  [ HTMX Request (POST/GET) ]
                                    |
                                    v
                           [ Django View ]
                                    |
                                    v
                     [ Update DB & Execute Business Logic ]
                                    |
                                    v
                    [ Render HTML Partial (list_content.html) ]
                                    |
                                    v
                    [ HTMX Swaps Element into DOM ]
                    [ CSS View Transitions smoothly animate ]
```

### Key Request Patterns:
1. **Full Page Navigations:** When a user first visits `/`, `shopping_list_view` renders `shopping/list.html` (which extends `base.html` and includes `list_content.html`).
2. **Action Requests (Got, Need, Skip, Add, Reorder):** Form submissions or buttons make HTMX requests with `hx-target="#shopping-list-content"` and `hx-swap="outerHTML transition:true"`.
3. **Partial View Rendering:** The view invokes `render_list_response()`, which renders only `templates/shopping/partials/list_content.html` and returns it directly to the browser.
4. **Out-of-Band (OOB) Toasts:** Flash notifications render via `<div id="toast-container" hx-swap-oob="beforeend">`, automatically appending notification pills to the screen without disrupting the list contents.

---

## 3. Service Layer Architecture

Business logic is cleanly separated from views and database models into specialized services:

### A. List Organization Service (`apps/shopping/services/list_organizer.py`)
Encapsulated in `ShoppingListOrganizer`:
* `partition_items(items)`: Partitions items into `need_items` (To Buy), `got_items` (In Cart), and `pantry_items` (Already Have / Skipped).
* `group_and_sort_need_items(need_items, group_by, shopping_list)`: Organizes active items into section headers (either by category or aisle number), applying custom drag-and-drop sort orders or heuristic department walking orders.
* `resolve_view_mode(request, requested_mode)`: Normalizes whether the user is in **In Store** (`ListMode.SHOPPING`) or **Pantry Check** (`ListMode.PANTRY`) mode.

### B. Store & Aisle Intelligence (`apps/shopping/services/store_service.py`)
* `resolve_store_aisle(store, item_name)`:
  1. Checks the local SQLite `StoreItemAisle` cache.
  2. If missing and the active store is a Kroger location with API credentials configured, queries the official **Kroger Developer API**.
  3. Caches the result in the database so future queries resolve instantly without network round-trips.
* `get_aisle_sort_key(aisle_name)`: Heuristic natural sorting key that sequences supermarket departments according to physical supermarket layouts:
  * Fresh perimeter entrance (Produce, Floral, Bakery, Deli, Meat: 10–40)
  * Numbered grocery center aisles (Aisle 1 through Aisle 30+: 100+)
  * Cold back perimeter (Frozen, Dairy: 200–210)
  * Miscellaneous/General (300+)
* `haversine_distance()` and `get_nearest_stores()`: Fast GPS coordinate distance calculation used by the "📍 Near Me" browser geolocation feature.

### C. Ingredient Categorizer (`apps/core/categorizer.py`)
* Uses a YAML dictionary index and partial keyword matching with head-noun tie-breaking to automatically categorize free-form grocery item names (e.g. `'organic bell pepper'` &rarr; `produce`, `'cheddar cheese'` &rarr; `dairy`).

---

## 4. State Machines and Enums

All workflow states and choices are represented as `models.TextChoices` in `apps/shopping/models.py`:

```python
class ItemStatus(models.TextChoices):
    NEED = "NEED", "Need"                    # Active in "To Buy" section
    GOT = "GOT", "Got"                      # Completed in "Got / Cart" section
    HAVE = "HAVE", "Already Have"           # Verified at home in "Already Have"
    DONT_NEED = "DONT_NEED", "Don't Need"   # Skipped for this trip

class ListMode(models.TextChoices):
    SHOPPING = "shopping", "In Store"       # Fast supermarket shopping
    PANTRY = "pantry", "Pantry Check"       # At-home inventory verification

class GroupBy(models.TextChoices):
    CATEGORY = "category", "By Category"    # Grouped by supermarket department
    AISLE = "aisle", "By Aisle"             # Grouped by physical store aisle
```

### Audit Tracking
Every state transition passes through `_set_item_audit(item, request)`:
* Records `status_changed_at` (current timestamp).
* Assigns `status_changed_by` to the Django user if authenticated, or `None` if anonymous.
* Records `status_changed_by_name` as the username or `"unknown"` (strictly avoiding "You" in stored database records).

---

## 5. UI Architecture & Color Palette

Shoppin uses high-density, accessible styling structured around three visual zones:

1. **Active Items ("To Buy"):**
   * Neutral monochrome slate (`bg-white`, `border-gray-300`, `bg-gray-100` headers).
   * Clear visual focus on items that still require action.
2. **Purchased Items ("Got / Cart"):**
   * Soft, desaturated mint-green (`bg-cart-bg` `#f2f8f4`, `bg-cart-header` `#e1f0e6`, `border-cart-border` `#6ee7b7`).
   * Communicates successful purchase without high-alarm colors.
3. **Pantry / Skipped Items ("Already Have / Skipped"):**
   * Soft, calm sky-blue (`bg-pantry-bg` `#f0f5fa`, `bg-pantry-header` `#e2ecf7`, `border-pantry-border` `#93c5fd`).
   * Symmetrically balances the mint-green section while replacing alarming amber/caution tones.

All semantic colors are defined in the `tailwind.config` block in `templates/base.html`, so changing theme colors across the application only requires updating a single config dictionary.

---

## 6. Development Workflow & Commands

* **Run Development Server:**
  ```powershell
  .\.venv\Scripts\python manage.py runserver 127.0.0.1:8000
  ```
* **Run Test Suite:**
  ```powershell
  .\.venv\Scripts\pytest
  ```
* **Run Linter:**
  ```powershell
  .\.venv\Scripts\ruff check .
  ```
