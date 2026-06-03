# Competitive Purchase Analysis (RFQ)

**Menu:** Purchase → RFQ / Competitive Analysis  
**URL prefix:** `/purchase/rfq/`

## Workflow

1. Create **RFQ** with lines (optionally pull from Material Requisition).
2. Enter **SupplierQuote** + **SupplierQuoteLine** per vendor.
3. **Comparison matrix** on RFQ detail — lowest price highlighted per line.
4. **Award** — per-line supplier selection with justification (price / lead time / quality).
5. **Convert to PO(s)** — one PO per awarded supplier.

## Permissions

Uses `purchase` module; award requires `approve` permission.
