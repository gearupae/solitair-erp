# Inter-entity Transfers

**Menu:** Inventory → Inter-entity Transfers  
**URL prefix:** `/inventory/inter-entity/`

## Prerequisites

- **Settings → Companies** — legal entities with optional intercompany receivable/payable GL accounts.
- **Warehouses** — link each warehouse to a `legal_entity` (Company).
- **InterEntityVatTreatment** — seeded codes (intra/inter emirate, designated zone, etc.).

## Workflow

1. **Draft** — source/destination entity + warehouses + lines.
2. **Approved** — source approval.
3. **In Transit** — stock-out at source + interco receivable GL (Dr interco recv, Cr inventory).
4. **Received** — stock-in at destination + interco payable GL.

## Reports

**Inventory → Inter-entity Transfers → Reconciliation** (`/inventory/inter-entity/reconciliation/`)

Configure intercompany accounts on each Company for full GL reconciliation.
