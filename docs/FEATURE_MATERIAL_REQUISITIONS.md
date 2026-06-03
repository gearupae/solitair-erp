# Material Requisitions

**Menu:** Inventory → Material Requisitions  
**URL prefix:** `/inventory/requisitions/`

## Workflow

1. **Draft** — requester creates MR with lines (any product item).
2. **Submitted** — sent for approval.
3. **Approved** — approver sets warehouse; line `qty_approved` defaults to requested qty.
4. **Partially Issued / Issued** — stock-out movements posted via `MaterialRequisitionIssue` events (partial issue supported).
5. **Closed / Rejected** — terminal states.

## Consumables

Existing **Consumable Requests** (`request_kind=consumable`) remain unchanged. New MRs use `request_kind=material`. Same underlying `ConsumableRequest` model and GL issue logic.

## Permissions

Uses `inventory` module: view, create, edit, approve (approve maps to edit in `PermissionChecker`).
