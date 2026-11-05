# Shoppin 🛒🍳

> **An intelligent, real-time collaborative grocery shopping list generator, recipe database, and meal planning platform.**

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Django Version](https://img.shields.io/badge/django-6.0%2B-forestgreen.svg)](https://www.djangoproject.com/)
[![Channels](https://img.shields.io/badge/channels-4.3%20%7C%20ASGI-orange.svg)](https://channels.readthedocs.io/)
[![HTMX](https://img.shields.io/badge/frontend-HTMX%202.0%20%2B%20TailwindCSS-3d72d7.svg)](https://htmx.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Test Suite](https://img.shields.io/badge/tests-309%20passed-brightgreen.svg)](tests/)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-black.svg)](https://github.com/astral-sh/ruff)
[![Accessibility: WCAG 2.1/2.2 AA](https://img.shields.io/badge/accessibility-WCAG%202.1%2F2.2%20AA-purple.svg)](https://www.w3.org/WAI/WCAG21/quickref/)

---

## Table of Contents

- [The Problem Shoppin Solves](#the-problem-shoppin-solves)
- [Key Features](#key-features)
- [System Architecture](#system-architecture)
- [Real-Time WebSocket & HTMX Synchronization](#real-time-websocket--htmx-synchronization)
- [Data Models & Entity Relationships](#data-models--entity-relationships)
- [Shopping Item Workflow & State Machine](#shopping-item-workflow--state-machine)
- [Supermarket Aisle Intelligence](#supermarket-aisle-intelligence)
- [Getting Started & Local Installation](#getting-started--local-installation)
- [Docker & Container Deployment](#docker--container-deployment)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Testing & Quality Assurance](#testing--quality-assurance)
- [Production Deployment & DevOps](#production-deployment--devops)
- [Accessibility & UI Design Standards](#accessibility--ui-design-standards)
- [Contributing](#contributing)
- [License](#license)

---

## The Problem Shoppin Solves

Modern household meal preparation and grocery shopping suffer from systemic friction:

1. **Disconnected Silos**: Recipes live in bookmarked websites or cookbooks, meal schedules exist on whiteboards or calendars, and grocery lists are kept in generic note apps. Bridging them requires tedious, manual transcription of ingredients.
2. **Pantry Blindness & Duplicate Purchases**: Traditional shopping apps only track what to buy. Shoppers repeatedly purchase ingredients they already had sitting in their pantry, or forget to buy the single missing staple needed for dinner.
3. **Inefficient Supermarket Navigation**: Standard shopping lists sort items alphabetically or by order of entry. Shoppers waste time zig-zagging back and forth across a large supermarket rather than moving in a natural sequence through departments and numbered aisles.
4. **Multi-Shopper Coordination Chaos**: When partners, roommates, or families shop together (or when one person shops while another checks the pantry at home), static lists lead to duplicate items, conflicting carts, and constant text messaging.
5. **Portion Math & Scalability Friction**: Doubling a recipe or cooking for a dinner party requires mental conversions for dozens of ingredients, making it easy to miscalculate quantities when combining items across multiple planned meals.
6. **Household Staple Drift**: Routine staples (milk, eggs, oats, paper towels) run out unpredictably because there is no automated schedule to refresh recurring essentials onto the active list.

**Shoppin solves these problems in a single, cohesive, open-source hypermedia application.** It combines web recipe scraping, fractional portion scaling, automated pantry verification, store-specific aisle routing, real-time WebSocket synchronization, and scheduled staple replenishment into an intuitive, accessible interface.

---

## Key Features

### 🛒 Hypermedia Shopping Experience
- **Server-Driven HTMX Interactivity**: Sub-millisecond response times with smooth CSS view transitions without the overhead of client-side JavaScript single-page application (SPA) frameworks.
- **Dual Workflow Modes**:
  - **In-Store Shopping Mode**: Optimized for one-thumb mobile execution (`Got` / `Skip`) while pushing a shopping cart through store aisles.
  - **Pantry Check Mode**: At-home pre-trip audit mode (`Have` / `Need` / `Skip`) to eliminate unnecessary purchases of items already on hand.
- **Dynamic Grouping & Drag-and-Drop**:
  - Group items dynamically **By Department/Category**, **By Store Aisle**, or **By Priority**.
  - Reorder items and entire sections using intuitive touch drag-and-drop (SortableJS) or accessible keyboard hotkeys (`Alt+Up` / `Alt+Down`).

### ⚡ Real-Time Multi-User Collaboration
- **Zero-Latency WebSocket Sync**: Built on **Django Channels** and **Daphne ASGI**. When one family member checks off an item at the supermarket, all connected devices update instantly.
- **Out-of-Band (OOB) Activity Notifications**: Live toast alerts inform collaborators in real time (e.g., *"Alex moved 'Sourdough Bread' to In Cart"*).
- **Client Echo Prevention**: Custom `X-Client-Id` header tracking prevents redundant DOM updates for the active user who initiated the action.

### 🗺️ Supermarket Aisle Intelligence & Store Proximity
- **Physical Store Aisle Mapping**: Automatically learns and maps grocery items to store-specific aisle numbers (e.g., *King Soopers Glendale: Produce Bay 4, Aisle 7, Dairy Wall*).
- **Natural Department Walking Sequences**: Heuristic path sequencer guides shoppers from fresh perimeter entrances (Produce, Bakery, Deli, Meat) through numbered grocery aisles to cold rear perimeter sections (Dairy, Frozen).
- **Live Kroger Developer API Integration**: Seamless lookups against live supermarket inventory APIs for verified aisle numbers.
- **GPS "Near Me" Location Finder**: Uses the browser Geolocation API and Haversine geodesic calculations to locate nearby supermarkets with interactive OpenStreetMap / Leaflet modal previews.

### 🍳 Recipe Engine & Provenance Tracking
- **Universal Recipe Web Scraper**: Paste any URL from hundreds of culinary websites to automatically extract title, servings, prep/cook times, directions, ingredients, and photography via `recipe-scrapers`.
- **Dynamic Portion Scaling**: Instantly scale recipe ingredients by $0.5\times$, $1\times$, $1.5\times$, $2\times$, or $3\times$ with automatic fractional quantity conversion.
- **Automated Nutritional Breakdown**: Estimates calories, carbohydrates, protein, fat, fiber, and sodium per serving.
- **Dietary & Equipment Tagging**: Comprehensive filters for cuisines, meal types, and dietary restrictions (vegetarian, vegan, kosher-parve, gluten-free, dairy-free).
- **Ingredient Provenance (`ShoppingListItemSource`)**: Retains complete lineage when recipes are added to the shopping list. Removing a recipe automatically removes only its associated ingredients without disturbing manual items or items shared with other dishes.

### 📅 Dynamic Meal Planning
- **Meal Composition**: Group recipes into structured meals (e.g., *"Monday Dinner: Chicken Piccata + Garlic Green Beans"*).
- **One-Click Cart Loading**: Transfer all missing ingredients for an entire meal plan directly into the active shopping list with a single click.
- **Dietary Balance Rules**: Configure guideline rules (e.g., *"Every dinner needs a green vegetable"*) to guide healthy household meal planning.
- **Meal Made History**: Mark meals as prepared to increment cooking counters and maintain a personal culinary logbook.

### 🔁 Recurring Preset Staple Lists
- **Household Staple Templates**: Maintain reusable lists of recurring essentials (e.g., *Weekly Dairy & Produce*, *Monthly Cleaning Supplies*).
- **Automated Scheduled Refresh**: Set recurring intervals (e.g., 7 days, 14 days, 30 days) with automated background execution to guarantee essentials are replenished before you run out.

### 👥 Multi-Tenant Collaborative Workspaces
- **Role-Based Access Control (RBAC)**:
  - **Owner**: Full administrative control over workspace settings, members, and deletion.
  - **Editor (Read-Write)**: Can modify shopping lists, add recipes, and plan meals.
  - **Viewer (Read-Only)**: Real-time visibility into lists and meal plans without edit permissions.
- **Automated Cart Retention Policy**: Configurable retention periods (e.g., auto-clean completed items after 7 days) to keep lists uncluttered.

### ♿ Accessibility & Inclusivity First
- **WCAG 2.1 & 2.2 AA Compliant**:
  - High-contrast text ($\ge 4.5:1$, using standard `text-gray-700` and `text-gray-950`).
  - Active control boundary contrast ($\ge 3:1$, `border-gray-400`).
  - Accessible name alignment (*Label in Name* WCAG 2.5.3).
  - Keyboard-accessible drag-and-drop alternatives (`Alt+ArrowUp` / `Alt+ArrowDown`).
  - Screen-reader friendly semantic landmarks and ARIA dialog traps.
- **Progressive Web App (PWA)**: Mobile-optimized touch targets, web manifest, and home-screen installability.

---

## System Architecture

Shoppin uses an asynchronous, hypermedia-driven architecture designed for high concurrency, low latency, and zero frontend build complexity:

```mermaid
flowchart TD
    subgraph Clients["Clients (Desktop, Mobile, Tablet)"]
        Browser["Modern Web Browser / PWA"]
        HTMX["HTMX 2.0 Engine"]
        WSClient["WebSocket Client (ws.js)"]
    end

    subgraph Edge["Reverse Proxy & TLS"]
        Caddy["Caddy Web Server (HTTPS / HTTP3 / Let's Encrypt)"]
    end

    subgraph AppServer["Application Layer (Daphne ASGI Server)"]
        Daphne["Daphne ASGI Process"]
        DjangoHTTP["Django 6 HTTP Request Pipeline"]
        DjangoChannels["Django Channels Consumer (/ws/shopping/)"]
    end

    subgraph ServiceLayer["Core Domain Services"]
        ListOrganizer["ListOrganizer Service"]
        StoreService["Store & Aisle Service"]
        RecipeService["Recipe & Scraper Service"]
        MealPlanService["MealPlan Service"]
        PresetService["Preset Scheduler Service"]
        Broadcaster["Broadcaster (Django Channels Group)"]
    end

    subgraph Storage["Persistence & Caching"]
        DB[("PostgreSQL / SQLite (WAL Mode)")]
        Redis[("Redis Channel Layer (Optional / Prod)")]
    end

    subgraph External["External APIs"]
        KrogerAPI["Kroger Developer API (Live Aisles)"]
        OSM["OpenStreetMap / Leaflet (Geocoding)"]
    end

    Browser -->|HTTP / HTTPS| Caddy
    Browser -->|WSS WebSocket| Caddy
    Caddy -->|Reverse Proxy :8000| Daphne
    Daphne -->|HTTP Handlers| DjangoHTTP
    Daphne -->|ASGI WebSocket| DjangoChannels

    DjangoHTTP --> ServiceLayer
    DjangoChannels --> Broadcaster

    ListOrganizer --> DB
    StoreService --> DB
    StoreService -.->|Store Lookup| KrogerAPI
    RecipeService --> DB
    MealPlanService --> DB
    PresetService --> DB

    Broadcaster -->|Publish Event| Redis
    Redis -->|Broadcast to Group| DjangoChannels
    DjangoChannels -->|Push HTML Partial| WSClient
    WSClient -->|Swap Element| Browser
```

---

## Real-Time WebSocket & HTMX Synchronization

Shoppin synchronizes state across multiple devices without requiring heavy client-side state managers:

```mermaid
sequenceDiagram
    autonumber
    actor UserA as Shopper A (In Store)
    participant DOM_A as Browser A (HTMX)
    participant Server as Daphne / Django
    participant ChannelLayer as Redis / In-Memory Channel Layer
    participant DOM_B as Browser B (At Home)
    actor UserB as Shopper B (Pantry)

    Note over UserA,UserB: Both clients connected via /ws/shopping/

    UserA->>DOM_A: Taps "Got" on "Apples"
    DOM_A->>Server: POST /shopping/items/42/status/ (X-Client-Id: client-A)
    Note over Server: Update ShoppingListItem status = GOT<br/>Update provenance & audit log

    Server-->>DOM_A: 200 OK (Rendered list_content.html partial)
    DOM_A->>DOM_A: HTMX swaps updated list & animates transition

    Server->>ChannelLayer: broadcast_shopping_list_update(origin_client="client-A", message="Shopper A moved Apples to Cart")
    ChannelLayer->>DOM_B: Push WebSocket JSON message
    Note over DOM_B: Detects origin_client != client-B

    DOM_B->>Server: GET /shopping/ (Fetch fresh partial)
    Server-->>DOM_B: 200 OK (Rendered list_content.html)
    DOM_B->>DOM_B: HTMX replaces list & displays out-of-band toast notification
    UserB->>DOM_B: Sees "Apples" moved to Cart in real time!
```

---

## Data Models & Entity Relationships

The relational domain model enforces strict multi-tenant workspace separation and complete ingredient provenance:

```mermaid
erDiagram
    User ||--o{ Workspace : owns
    User ||--o{ WorkspaceMember : belongs_to
    Workspace ||--o{ WorkspaceMember : has
    Workspace ||--o{ ShoppingList : contains
    Workspace ||--o{ MealPlan : contains

    ShoppingList ||--o{ ShoppingListItem : contains
    StoreLocation ||--o{ ShoppingList : active_store
    StoreLocation ||--o{ StoreItemAisle : maps

    ShoppingListItem ||--o{ ShoppingListItemSource : tracks_sources
    Recipe ||--o{ ShoppingListItemSource : originates_from
    MealDish ||--o{ ShoppingListItemSource : originates_from
    ShoppingList ||--o{ ShoppingListItemSource : originates_preset

    Recipe ||--o{ Ingredient : contains
    Recipe ||--o{ RecipeRating : rated_by
    Recipe ||--o{ RecipeComment : commented_by
    Recipe ||--o{ RecipeMadeLog : cooked_log

    MealPlan ||--o{ Meal : contains
    MealPlan ||--o{ MealPlanRule : enforces
    Meal ||--o{ MealDish : schedules
    Recipe ||--o{ MealDish : cooked_in

    User {
        int id PK
        string username
        string email
    }

    Workspace {
        int id PK
        string name
        int owner_id FK
        int completed_items_retention_days
        datetime created_at
    }

    WorkspaceMember {
        int id PK
        int workspace_id FK
        int user_id FK
        string role "viewer | editor"
    }

    ShoppingList {
        int id PK
        int workspace_id FK
        int owner_id FK
        string name
        boolean is_preset
        boolean schedule_enabled
        int schedule_interval_days
        datetime schedule_next_due
    }

    ShoppingListItem {
        int id PK
        int shopping_list_id FK
        string name
        string status "NEED | GOT | HAVE | DONT_NEED"
        string category
        string aisle
        decimal amount
        string amount_unit
        boolean priority
        int order
    }

    ShoppingListItemSource {
        int id PK
        int item_id FK
        int recipe_id FK
        int meal_dish_id FK
        int preset_list_id FK
        decimal multiplier
    }

    Recipe {
        int id PK
        string name
        string slug
        int portions
        int prep_time_minutes
        int cook_time_minutes
        int calories_per_serving
        string difficulty_level
        json dietary_restrictions
        json meal_type
    }

    MealPlan {
        int id PK
        int workspace_id FK
        string name
    }

    Meal {
        int id PK
        int meal_plan_id FK
        string name
        string emoji
        int order
    }
```

---

## Shopping Item Workflow & State Machine

Items transition seamlessly through four distinct workflow states depending on whether the user is at home checking the pantry or in the store shopping:

```mermaid
stateDiagram-v2
    [*] --> NEED : Item added to list

    state "To Buy (Active Section)" as NEED {
        [*] --> Unchecked
        Unchecked --> HighPriority : Flag Priority
        HighPriority --> Unchecked : Remove Priority
    }

    NEED --> GOT : In-Store: "Got" (Purchased)
    NEED --> HAVE : Pantry Check: "Have" (Already in Pantry)
    NEED --> DONT_NEED : "Skip" (Deferred / Not Needed)

    state "In Cart (Got Section)" as GOT {
        GOT --> NEED : "Need" (Move back to list)
    }

    state "Pantry / Skipped Section" as HomePantry {
        HAVE --> NEED : "Need" (Pantry empty, must buy)
        DONT_NEED --> NEED : "Need" (Restore item)
    }

    GOT --> [*] : Auto-removed after retention period
    HAVE --> [*] : Auto-removed after retention period
```

---

## Supermarket Aisle Intelligence

Shoppin eliminates random zig-zagging in supermarkets by organizing items in the exact physical walking order of modern grocery stores:

```
[ Entrance / Perimeter ]
    ├── 10: Produce & Floral (Apples, Herbs, Salad)
    ├── 20: Bakery (Bread, Tortillas, Bagels)
    ├── 30: Deli & Prepared Foods (Hummus, Sliced Turkey)
    └── 40: Fresh Meat & Seafood (Chicken Breast, Salmon)

[ Center Grocery Aisles ]
    ├── 101: Aisle 1 (Canned Goods, Soup, Broth)
    ├── 102: Aisle 2 (Pasta, Rice, International)
    ├── 103: Aisle 3 (Baking, Spices, Oils, Vinegar)
    ├── 104: Aisle 4 (Breakfast, Cereals, Coffee, Tea)
    └── 105+: Aisles 5+ (Snacks, Beverages, Paper Goods)

[ Rear Cold Perimeter ]
    ├── 200: Dairy & Eggs (Milk, Cheese, Butter, Yogurt)
    └── 210: Frozen Foods (Frozen Veggies, Ice Cream)

[ Miscellaneous / Unknown ]
    └── 300+: Unmapped or Specialty Items
```

Shoppers can toggle between **By Category** (standard department classification) and **By Aisle** (store-specific aisle numbers) with a single tap.

---

## Getting Started & Local Installation

### Prerequisites

- **Python 3.12+**
- **Git**
- **SQLite** (bundled with Python) or **PostgreSQL 14+**
- *(Optional)* **Redis** for WebSocket broadcasting in multi-worker environments (in-memory channel layer is enabled by default for development)

### 1. Clone the Repository

```bash
git clone https://github.com/mklopot/shoppin.git
cd shoppin
```

### 2. Set Up a Virtual Environment

```bash
# On Linux / macOS
python3 -m venv .venv
source .venv/bin/activate

# On Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Dependencies & Pre-Commit Hook

```bash
# Install package in editable mode with development dependencies
pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"

# Configure Git pre-commit hooks to run Ruff automatically
git config core.hooksPath .githooks
```

### 4. Configure Environment Variables

Copy the example development environment file:

```bash
cp .env.example .env
```

Key variables to check in `.env`:

```ini
DJANGO_SECRET_KEY=development-secret-key-change-in-production
DJANGO_DEBUG=True
DEV_AUTO_LOGIN=False

# Optional: Kroger API for live supermarket aisle lookups
KROGER_CLIENT_ID=
KROGER_CLIENT_SECRET=
```

### 5. Run Migrations & Import Initial Data

```bash
# Apply database schema
python manage.py migrate

# Seed sample recipes and preset grocery lists
python manage.py import_recipes

# (Optional) Seed realistic multi-persona test accounts
python manage.py seed_personas
```

### 6. Create a Superuser & Run the Server

```bash
# Create admin account
python manage.py createsuperuser

# Start the Daphne ASGI development server
python manage.py runserver 127.0.0.1:8000
```

Open your browser and navigate to **`http://127.0.0.1:8000/`**.

---

## Docker & Container Deployment

Shoppin provides a production-grade multi-stage `Dockerfile` and `docker-compose.prod.yml` that orchestrates:
- **Caddy**: Reverse proxy with automatic Let's Encrypt SSL/TLS, HTTP/3, and zero-downtime hot reloads.
- **Web (`shoppin_web`)**: Multi-stage unprivileged container running Daphne ASGI.
- **Database (`shoppin_postgres`)**: PostgreSQL 16 Alpine.
- **Cache / Channels (`shoppin_redis`)**: Redis 7 Alpine.

### Running with Docker Compose

1. Create production environment file:
   ```bash
   cp .env.prod.example .env.prod
   # Edit .env.prod with your production domain, PostgreSQL password, and secrets
   ```

2. Start the container stack:
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

3. Initialize migrations and static files inside the container:
   ```bash
   docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput
   docker compose -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
   ```

---

## Configuration & Environment Variables

All configuration is managed through standard environment variables read in `config/settings.py`:

| Variable | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| `DJANGO_SECRET_KEY` | **Yes** | *insecure default* | Cryptographic signing key for Django sessions and tokens. |
| `DJANGO_DEBUG` | No | `False` | Enable or disable Django debug mode. |
| `ALLOWED_HOSTS` | No | `localhost,127.0.0.1` | Comma-separated list of valid host/domain names. |
| `CSRF_TRUSTED_ORIGINS` | No | `http://localhost:8000` | Comma-separated list of origins trusted for CSRF validation. |
| `DATABASE_URL` | No | `sqlite:///db.sqlite3` | Database connection URL (`postgres://user:pass@host:5432/db`). |
| `REDIS_URL` | No | `None` (uses in-memory) | Redis connection URL (`redis://localhost:6379/0`) for Channel Layers. |
| `DOMAIN_NAME` | No | `localhost` | Canonical domain used by Caddy for automated SSL certificates. |
| `DEV_AUTO_LOGIN` | No | `False` | Auto-authenticates as admin in local development when set to `True`. |
| `GOOGLE_CLIENT_ID` | No | `""` | Google OAuth 2.0 client ID for social sign-in. |
| `GOOGLE_CLIENT_SECRET`| No | `""` | Google OAuth 2.0 client secret. |
| `KROGER_CLIENT_ID` | No | `""` | Kroger Developer API client ID for live supermarket aisle lookups. |
| `KROGER_CLIENT_SECRET`| No | `""` | Kroger Developer API client secret. |
| `S3_BACKUP_BUCKET` | No | `""` | AWS S3 bucket for automated database backups (`scripts/backup-db.sh`). |

---

## Testing & Quality Assurance

Shoppin maintains a 100% passing test suite across all application domains:

```bash
# Run the entire test suite with parallel execution (8 workers)
pytest

# Run targeted test suites
pytest tests/test_shopping_ui.py
pytest tests/test_mealplans.py
pytest tests/test_recipes.py
pytest tests/test_store_aisles.py
pytest tests/test_websockets.py
pytest tests/test_presets.py

# Run static linting with Ruff (zero warnings policy)
ruff check .

# Automatically apply Ruff safe fixes
ruff check . --fix
```

### Git Pre-Commit Hook

A pre-commit hook is located at `.githooks/pre-commit`. It executes `ruff check .` before every commit to guarantee that unsorted imports (`I001`), unused imports (`F401`), or style violations never enter the repository history.

---

## Production Deployment & DevOps

Shoppin is deployed to production via an automated CI/CD pipeline defined in `.github/workflows/deploy.yml`:

1. **Continuous Integration**:
   - Every push to `v2-django` or `main` automatically runs Ruff linting and the full Pytest test suite across all 309+ tests.
2. **Zero-Downtime Deployment**:
   - On successful test completion, the deployment runner connects to the production instance (e.g. AWS Lightsail / EC2) and invokes `deploy/lightsail/update.sh`.
   - The update script:
     - Pulls the latest git commit.
     - Installs updated Python packages.
     - Runs database migrations (`manage.py migrate`).
     - Imports newly added recipes.
     - Collects static files (`manage.py collectstatic`).
     - Performs a zero-downtime hot reload of the **Caddy** web server.
     - Gracefully restarts the **Daphne ASGI** service.
     - Verifies health via the `/health/` probe.
3. **Automated Health Probes**:
   - Endpoint: `/health/` returns `{"status": "healthy", "database": "connected"}` with HTTP 200.

---

## Accessibility & UI Design Standards

Accessibility is a primary design requirement in Shoppin:

- **Contrast Ratios**:
  - Regular body text and interactive labels strictly meet or exceed **WCAG AA 4.5:1** contrast ratios against white/light backgrounds (using Tailwind `text-gray-700` which provides an optimal **9.0:1** luminosity ratio).
  - Visual boundaries of active inputs, checkboxes, and buttons strictly meet or exceed **WCAG AA 3:1** non-text contrast (`border-gray-400`).
- **Label in Name (WCAG 2.5.3)**:
  - All interactive buttons with `aria-label` attributes either match or begin with their visible button text (e.g., button labeled `Got` has `aria-label="Got: Mark {item} as bought"`).
- **Keyboard Drag-and-Drop Alternative (WCAG 2.1.1, 2.5.7)**:
  - All drag handles are keyboard focusable (`tabindex="0" role="button"`). Users can reorder shopping items and categories directly using `Alt+ArrowUp` and `Alt+ArrowDown`.
- **Motion Reduction**:
  - Respects user preferences via CSS `prefers-reduced-motion` to disable non-essential animations.

---

## Contributing

We welcome community contributions, bug reports, and feature suggestions!

1. **Fork the Repository** and create your branch from `v2-django`:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. **Ensure Code Quality Standards**:
   ```bash
   ruff check .
   pytest
   ```
3. **Commit Your Changes** with clear, semantic commit messages:
   ```bash
   git commit -m "feat(shopping): add aisle search filter"
   ```
4. **Push to Your Fork** and open a Pull Request.

---

## License

Shoppin is licensed under the [MIT License](LICENSE).  
Copyright &copy; 2024–2026 Waldorf Wellington. All rights reserved.
