# Minimum Viable Product (MVP) Specification

## 1. Project Overview & Objectives

**ControlStock** is a dedicated inventory management system engineered for apparel (clothing) e-commerce businesses.

### Core Objectives
1. **Engineering Portfolio Showcase:** Demonstrate production-grade backend engineering practices, clean modular architecture, rigorous database modeling, concurrency management, automated test coverage, and clear documentation.
2. **Production-Ready E-commerce Foundation:** Serve as a functional, real-world inventory control engine for an active clothing brand, built to eliminate common pitfalls such as overselling and lack of stock visibility.

---

## 2. Domain Model & Apparel Concepts

Traditional inventory management systems often treat products as single-item entities (`id`, `name`, `quantity`). In apparel retail, this model fails. Clothing items require a **parent-variant structure** (Matrix/Grid):

```mermaid
flowchart TD
    Parent["Parent Product\n(e.g., Oversized Heavyweight T-Shirt)"]
    Cat["Category: T-Shirts"] --> Parent
    
    Parent --> V1["Variant SKU: TSH-OVR-BLK-P\nColor: Black | Size: P\nCost: $30.00 | Retail: $89.90"]
    Parent --> V2["Variant SKU: TSH-OVR-BLK-M\nColor: Black | Size: M\nCost: $30.00 | Retail: $89.90"]
    Parent --> V3["Variant SKU: TSH-OVR-WHT-G\nColor: White | Size: G\nCost: $30.00 | Retail: $89.90"]
    Parent --> V4["Variant SKU: TSH-OVR-WHT-G1\nColor: White | Size: G1 (Special)\nCost: $35.00 | Retail: $99.90"]
```

### 2.1 Parent Product
* **Fields:** `id`, `name`, `slug`, `description`, `category_id`, `brand`, `is_active`, `created_at`, `updated_at`.
* Represents the conceptual garment line.

### 2.2 Apparel Variants (SKU)
* **Fields:** `id`, `product_id`, `sku`, `color_name`, `color_hex`, `size`, `barcode`, `cost_price`, `retail_price`, `image_url`, `min_safety_stock`, `is_active`.
* **Size Support:** Flexible text representation accommodating both letter-based sizing (`PP`, `P`, `M`, `G`, `GG`, `XGG`) and numerical sizing (`34`, `36`, `38`, `40`, `42` for pants, shorts, and footwear).
* **SKU Code Generation:** Auto-generated standardized pattern (e.g., `[PRD-SLUG]-[COLOR]-[SIZE]`) with manual override capability.
* **Variant-Level Pricing:** Each variant holds its specific `cost_price` and `retail_price`, supporting price adjustments for plus-size or specialized fabric variations.
* **UX Image Association:** Images are linked per color variation, allowing frontend clients to update product visuals dynamically when a customer switches color options.

---

## 3. Stock Balance Engine & Concurrency Control

```mermaid
flowchart LR
    Inbound["Inbound Restock"] --> Physical["Physical Stock\n(Units on shelf)"]
    Physical --> Available["Available Stock\n(Physical - Reserved)"]
    Checkout["Customer Checkout (PIX)"] --> Reserved["Reserved Stock\n(10-min TTL hold)"]
    Reserved --> Available
    PaymentConfirmed["Payment Confirmed"] --> Sold["Outbound Sale\n(Physical - 1, Reserved - 1)"]
    PaymentExpired["PIX Expired / Cancelled"] --> Release["Stock Release\n(Reserved - 1)"]
```

### 3.1 Three-Tier Inventory Balances
To prevent overselling (*selling inventory that does not exist or is already committed*):
1. **Physical Quantity (`physical_qty`):** Total real units physically present in the stockroom/warehouse.
2. **Reserved Quantity (`reserved_qty`):** Units held for unfinalized checkouts pending payment confirmation.
3. **Available Quantity (`available_qty`):** Calculated dynamically as:
   $$\text{Available} = \text{Physical} - \text{Reserved}$$
   This is the exact number exposed to the e-commerce storefront for customer purchase.

### 3.2 Payment & Reservation Policies
* **Instant Payments (Credit / Debit Cards):** Immediate settlement. Decrements `physical_qty` directly upon transaction approval.
* **Asynchronous Payments (PIX):**
  * Initiating checkout locks the required units under `reserved_qty` with a **10-minute Time-To-Live (TTL)**.
  * Payment webhook confirmed within 10 minutes $\rightarrow$ converts reservation into confirmed sale: decrements both `physical_qty` and `reserved_qty`.
  * TTL elapsed without payment $\rightarrow$ release event: decrements `reserved_qty`, returning the units to `available_qty`.
* **Bank Slips (Boleto):** Excluded from MVP scope to avoid prolonged inventory holds.

### 3.3 Zero-Negative Guarantee (Strict Database Integrity)
The system strictly prohibits negative balances under any circumstances. Enforced via database-level check constraints:
```sql
CONSTRAINT chk_physical_non_negative CHECK (physical_quantity >= 0);
CONSTRAINT chk_reserved_non_negative CHECK (reserved_quantity >= 0);
CONSTRAINT chk_reserved_not_exceed_physical CHECK (reserved_quantity <= physical_quantity);
```

---

## 4. Immutable Inventory Ledger (Audit Trail)

Stock balances are never modified with arbitrary `UPDATE` statements without provenance. Every change in stock quantity produces an immutable **Movement Event** record.

### Movement Types
| Type Code | Balance Impact | Description |
| :--- | :--- | :--- |
| `INBOUND_PURCHASE` | `+ physical_qty` | Arrival of manufactured/purchased batch from suppliers. Records supplier batch unit cost. |
| `OUTBOUND_SALE` | `- physical_qty`, `- reserved_qty` | Order payment settled. Units deducted permanently. |
| `STOCK_RESERVE` | `+ reserved_qty` | Customer initiates PIX checkout. Units held for 10 minutes. |
| `STOCK_RELEASE` | `- reserved_qty` | PIX expired or customer cancels checkout prior to payment. |
| `CUSTOMER_RETURN` | `+ physical_qty` | Return or size exchange accepted back into inventory. Requires mandatory classification reason. |
| `LOSS_DEFECT` | `- physical_qty` | Garment damaged, fabric flawed, or lost. Deducted with reason note. |
| `INVENTORY_ADJUSTMENT` | `+/- physical_qty` | Stockroom physical count reconciliation (cycle count). |

### Mandatory Customer Return Reasons
Garment returns must be classified to diagnose supplier quality and pattern grading issues:
* `WRONG_SIZE` (Customer ordered incorrect size / pattern runs small/large)
* `FABRIC_DEFECT` (Manufacturing defect, seam tear, color bleeding)
* `NOT_AS_PICTURED` (Color or styling differs from expectations)
* `CUSTOMER_REGRET` (Standard statutory withdrawal)

---

## 5. Functional Requirements (FR)

### Module 1: Product & Apparel Matrix Management
* **FR-01:** The system shall allow creating, updating, retrieving, and deactivating parent products and categories.
* **FR-02:** The system shall generate variant combinations (size $\times$ color) under a parent product.
* **FR-03:** The system shall auto-generate unique SKU codes following the pattern `[PRODUCT_SLUG]-[COLOR]-[SIZE]` while permitting manual overrides.
* **FR-04:** The system shall store distinct cost and retail prices per variant.
* **FR-05:** The system shall associate image references to specific color variants.

### Module 2: Transactional Stock Management
* **FR-06:** The system shall register inbound purchase shipments (`INBOUND_PURCHASE`), updating physical quantities and logging supplier unit purchase costs.
* **FR-07:** The system shall create temporary stock reservations (`STOCK_RESERVE`) with a 10-minute expiration for PIX checkouts.
* **FR-08:** The system shall release expired reservations (`STOCK_RELEASE`) back to available stock.
* **FR-09:** The system shall confirm sales (`OUTBOUND_SALE`), atomically decrementing physical and reserved balances.
* **FR-10:** The system shall register garment returns (`CUSTOMER_RETURN`) requiring a structured reason.
* **FR-11:** The system shall register inventory adjustments and fabric loss/defects (`LOSS_DEFECT`).

### Module 3: Alerts, Metrics & Valuation
* **FR-12:** The system shall evaluate stock balances against `min_safety_stock` thresholds and provide a queryable list of items in critical rupture status.
* **FR-13:** The system shall compute total inventory valuation:
  * Total physical units in stock.
  * Total invested capital ($\sum (\text{physical\_qty} \times \text{cost\_price})$).
  * Total gross retail potential ($\sum (\text{physical\_qty} \times \text{retail\_price})$).
  * Projected gross margin percentage.
* **FR-14:** The system shall provide filtering of stock positions by **Category** and **Stock Status** (`IN_STOCK`, `LOW_STOCK`, `OUT_OF_STOCK`).

---

## 6. Non-Functional Requirements (NFR)

* **NFR-01 (ACID Transactions & Row Locking):** All balance mutations and reservations must execute inside strict database transactions using pessimistic row-level locking (`SELECT ... FOR UPDATE`) to prevent race conditions during concurrent checkouts.
* **NFR-02 (Zero Negative Balances):** Guaranteed at both the application domain layer and database constraint layer.
* **NFR-03 (Automated Test Coverage):** Minimum of 80% test coverage across unit tests (business rules) and integration tests (database transactions, API endpoints).
* **NFR-04 (API Specification & Contracts):** 100% compliant OpenAPI 3.1 / Swagger documentation generated directly by FastAPI via Pydantic schemas.
* **NFR-05 (Stateless Architecture):** The backend API must be entirely stateless, container-ready, and configurable strictly via environment variables.

---

## 7. Architecture & Directory Blueprint

```text
ControlStock/
├── .github/
│   └── workflows/
│       └── ci.yml                     # GitHub Actions CI for Ruff & Pytest
├── docs/
│   └── MVP.md                         # This specification document
├── src/
│   └── control_stock/
│       ├── __init__.py
│       ├── main.py                    # FastAPI application entrypoint
│       ├── core/                      # Core configuration and database engine
│       │   ├── config.py              # Environment variables via pydantic-settings
│       │   └── database.py            # SQLAlchemy engine, session maker, base model
│       └── modules/                   # Domain modules (clean modular structure)
│           ├── products/              # Products and categories domain
│           │   ├── models.py
│           │   ├── schemas.py
│           │   ├── services.py
│           │   └── router.py
│           ├── variants/              # Apparel variants, sizes, and SKUs
│           │   ├── models.py
│           │   ├── schemas.py
│           │   ├── services.py
│           │   └── router.py
│           ├── inventory/             # Stock balances, reservations, and ledger
│           │   ├── models.py
│           │   ├── schemas.py
│           │   ├── services.py
│           │   └── router.py
│           └── reports/               # Stockout alerts and financial valuation
│               ├── schemas.py
│               ├── services.py
│               └── router.py
├── alembic/                           # Database migration scripts
├── tests/
│   ├── conftest.py                    # Pytest fixtures and test database setup
│   ├── unit/                          # Isolated business rule unit tests
│   └── integration/                   # Endpoint and transactional database tests
├── .env.example                       # Documented environment variables template
├── docker-compose.yml                 # Local development PostgreSQL service
├── Dockerfile                         # Container build instructions
├── requirements.txt                   # Production dependencies
└── README.md                          # Repository landing page
```

---

## 8. Technology Decisions & Rationale

| Decision | Selected Choice | Rationale |
| :--- | :--- | :--- |
| **Language** | Python 3.11+ | Clean syntax, robust static typing (`typing`, `Self`), high developer velocity. |
| **API Framework** | FastAPI | High async performance, automatic Swagger/OpenAPI documentation, seamless Pydantic integration. |
| **Validation** | Pydantic v2 | Rust-core serialization and deserialization, strict runtime validation. |
| **Persistence** | SQLAlchemy 2.0 | Modern declarative syntax (`Mapped`, `mapped_column`), explicit transaction control, robust connection pooling. |
| **Database** | PostgreSQL 16 | Relational standard for transactional integrity, row-level locks, and domain check constraints. |
| **Migrations** | Alembic | Track, audit, and roll forward/backward database schema modifications. |
| **Container** | Docker Compose | Ensures identical local development environment across contributors. |
| **CI / Quality** | Ruff + Pytest | Millisecond-level linting and formatting; comprehensive automated test execution in CI. |
| **Frontend** | React / Next.js | Modern, responsive client dashboard for store operations and management (planned for Phase 8). |
