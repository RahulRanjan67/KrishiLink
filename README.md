# KrishiLink

KrishiLink is a prototype developed while exploring **Smart India Hackathon Problem Statement 26132 — “Strengthening market linkages and price discovery for farmers.”**

The project explores how a digital workflow could connect **farmers, FPOs, and buyers** across the agricultural selling process. The current prototype focuses on the transaction-enablement side of the problem: buyer demand, FPO aggregation, quality information, offers, deal execution, dispatch, delivery, simulated payments, and dispute handling.

> **Development note**
> KrishiLink was developed as an **AI-assisted prototype using Antigravity and AI development tools**. I directed the problem breakdown, feature scope, workflow, architecture, and UI structure, and also participated in implementation refinement, function tuning, HTML/CSS review, debugging, and testing. AI assistance was used extensively for implementation generation and iteration. The repository is intentionally presented as a prototype rather than as production software or as a claim of fully independent implementation.

## What the prototype demonstrates

A seeded end-to-end happy path can be explored across four roles:

**Buyer → FPO → Farmers → Buyer**

1. A buyer publishes a crop requirement.
2. An FPO reviews the requirement and creates a collection lot.
3. Farmers contribute available crop quantities to the lot.
4. The FPO records a manual quality inspection passport.
5. Buyers submit offers against the inspected lot.
6. The FPO accepts an offer and creates a deal.
7. The FPO records dispatch details.
8. The buyer confirms delivery.
9. The system creates proportional farmer payouts.
10. The FPO/admin marks the simulated payouts as paid.
11. Users can raise and resolve disputes.

The prototype also includes role-based dashboards, notifications, help content, activity logging, buyer verification, deterministic matching scores, and seeded demonstration data.

## Scope relative to the SIH problem statement

The SIH problem statement describes a broader market-intelligence and transaction-enablement solution involving areas such as price intelligence, buyer demand, quality requirements, logistics and storage options, localized price trends, buyer matching, lot creation, quality grading, offers, payment tracking, and grievance processes.

KrishiLink implements a **working prototype subset** of that vision. It does not currently provide live mandi or market feeds, real-time price intelligence, external buyer verification, production logistics integrations, storage discovery, real payment gateways, or production-grade messaging/API integrations.

## Tech stack

- **Python**
- **FastAPI**
- **Jinja2** templates
- **HTML / CSS / JavaScript**
- **Bootstrap-style UI components and layouts**
- **SQLite**
- **Pydantic** validation
- **Starlette SessionMiddleware** for signed cookie sessions
- **unittest** for basic service-layer tests

The application intentionally keeps the architecture small and readable for prototype exploration. Database access uses direct SQLite queries rather than an ORM.

## Project structure

```text
KrishiLink/
├── ai/                         # Intentionally disabled future-AI interfaces
├── static/                     # Frontend assets
├── templates/                  # Jinja2 pages and role-specific views
├── database.py                 # SQLite schema, queries, and seed helpers
├── main.py                     # FastAPI application and routes
├── services.py                 # Business rules and transaction helpers
├── seed_data.py                # Standalone demo-data seeding script
├── requirements.txt            # Python dependencies
├── .env.example                # Environment variable template
├── .gitignore
├── DEVELOPMENT.md              # Development and AI-assistance notes
└── README.md
```

## Requirements

- Python 3.10+ recommended
- `pip`


## Setup

### 1. Clone the repository

```bash
git clone <https://github.com/RahulRanjan67/KrishiLink>
cd KrishiLink
```

### 2. Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure the session secret

Copy `.env.example` to `.env` and replace the placeholder value for `SESSION_SECRET` with a long random value.

For example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The application **requires `SESSION_SECRET`** and rejects values shorter than 32 characters.

`.env` is ignored by Git, so your local session secret will not be committed.

### 5. Start the application

```bash
python main.py
```

The default server is:

```text
http://127.0.0.1:8080/api
```

Alternatively, run the FastAPI application with Uvicorn directly:

```bash
uvicorn main:app --host 127.0.0.1 --port 8080
```

The application creates its SQLite database automatically on first startup and seeds the demonstration data when the database is empty.

## Demo accounts

All seeded demo accounts use the password:

```text
password123
```

| Role | Email | Purpose |
|---|---|---|
| Farmer | `farmer1@demo.com` | Farmer inventory and payout flow |
| FPO | `fpo@demo.com` | Requirement, aggregation, inspection, and deal flow |
| Buyer | `buyer@demo.com` | Demand, lots, offers, and delivery flow |
| Buyer | `procurement@demo.com` | Alternate buyer for offer comparisons |
| Buyer | `exports@demo.com` | Unverified buyer example |
| Admin | `admin@demo.com` | Verification, monitoring, and dispute resolution |

These credentials are **demo-only** and must not be reused for real deployments.

## Useful URLs

The application is mounted under `/api` by default.

```text
/api                  → redirect to the current user's dashboard
/api/login            → sign in
/api/register         → create a farmer or buyer account
/api/farmer           → farmer dashboard
/api/fpo              → FPO dashboard
/api/buyer            → buyer dashboard
/api/admin            → admin dashboard
/api/notifications    → notifications
/api/disputes         → dispute workflow
/api/healthz          → health check
```

## Data and reset behaviour

The SQLite database is created at:

```text
data/krishilink.db
```

The `data/` directory is ignored by Git. To reset the local demo environment, stop the application and delete the database:

```text
data/krishilink.db
```

On the next startup, the schema and seeded demonstration data will be recreated.

You can also reseed explicitly with:

```bash
python seed_data.py
```

## Design choices

- **Demand-first workflow:** buyer requirements drive aggregation rather than requiring farmers to guess where to sell.
- **FPO aggregation:** multiple farmer deposits can be pooled into a single lot.
- **Controlled lot states:** the service layer restricts major lot transitions.
- **Manual quality passport:** the prototype records FPO-entered grade and moisture information instead of claiming laboratory certification.
- **Simulated payouts:** farmer payments are calculated proportionally from deal value and contribution quantity.
- **Signed cookie sessions:** authentication is kept simple for prototype use with Starlette session middleware.
- **SQLite + direct SQL:** chosen for low setup overhead and readability.

## Prototype limitations

This repository should not be treated as production software. Important limitations include:

- SQLite is used as the application database.
- Password hashing is a simple salted SHA-256 demonstration and is not a production password-storage design.
- Payments are simulated; no bank, UPI, escrow, or payment gateway is connected.
- Quality inspection is manually entered by the FPO.
- There are no live mandi-price or market-data integrations.
- Buyer verification is a local prototype workflow rather than an external identity or credential verification service.
- There are no production messaging, logistics-provider, storage-provider, or GPS integrations.
- The included test suite is intentionally small.
- Authorization and workflow checks would need to be expanded before any real-world deployment.

## Future AI interfaces

The `ai/` directory contains intentionally disabled interfaces for possible future features such as buyer-requirement parsing, inventory search, deterministic-match explanations, and guided help.

These interfaces are **not required for the current application flow**. Any future AI-generated value should pass through the same validation and business-rule layer as normal user input.

