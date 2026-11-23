# ControlStock - E-commerce Inventory Management System

ControlStock is an inventory management backend system designed specifically for apparel (clothing) e-commerce businesses. It provides transactional inventory control, clothing variation matrices (Size/Color/SKU), stock reservation workflows, and financial valuation.

Designed with a dual purpose:
1. **Software Engineering Showcase:** Clean architecture, strict domain modeling, ACID transactions with concurrency locks, automated tests, and CI/CD pipelines.
2. **Production-Ready Foundation:** Practical, battle-tested domain logic tailored for clothing retail operations.

---

## Current Status

- **Phase:** Phase 1 - Architecture & MVP Specification
- **Current Branch:** `feat/Defining_MVP`
- **Specification Document:** Detailed requirements and technical architecture can be found in [docs/MVP.md].

---

## Tech Stack

| Layer | Technology | Purpose |
| :--- | :--- | :--- |
| **Language** | Python 3.11+ | Modern type annotations, async support |
| **API Framework** | FastAPI | High-performance async REST API, auto-generated OpenAPI/Swagger |
| **Data Validation** | Pydantic v2 | High-speed contract serialization and strict data validation |
| **ORM / Data Access** | SQLAlchemy 2.0 | Type-safe declarative mapping, transactional integrity |
| **Database Migrations** | Alembic | Version-controlled database schema migrations |
| **Database** | PostgreSQL 16 | ACID compliance, check constraints, row-level concurrency locks |
| **Containerization** | Docker & Docker Compose | Reproducible local development environment |
| **Quality & Tests** | Pytest, Ruff | Automated linting, formatting, and unit/integration testing |
| **Frontend (Future)** | React / Next.js | Modern web interface for store management |

---

## Key Features (MVP)

- **Clothing Matrix Catalog:** Parent products with variant combinations (Sizes: letters and numbers, Colors/Prints, individual cost/retail pricing, and auto-generated SKUs).
- **Three-Tier Stock Balance:** Real-time tracking of `Physical`, `Reserved`, and `Available` (`Physical - Reserved`) quantities.
- **Stock Reservation Engine:** 10-minute temporary reservation window for PIX checkout, with instantaneous settlement for credit/debit cards.
- **Zero-Negative Guarantee:** Database-level check constraints preventing negative inventory balances under any circumstance.
- **Immutable Inventory Ledger:** Audit trail tracking every inbound batch, outbound order, customer return with mandatory reason, and physical adjustment.
- **Reporting & Alerts:** Low-stock threshold alerts, valuation reports (total invested cost vs. potential retail revenue), and category/status filtering.


