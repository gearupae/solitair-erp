# Goods Receipt Notes (GRN)

**Menu:** Purchase → Goods Receipt Notes  
**URL prefix:** `/purchase/grn/`

## Workflow

1. Receive goods on a PO (**Purchase → Purchase Orders → Receive**) — creates `GoodsReceiptNote` + existing stock-in / GRN clearing GL.
2. **Posted** — stock movements linked on `GRNLine`; partial receipts supported (multiple GRNs per PO).
3. **Cancelled** — reverses stock (adjustment out) and journal via `JournalEntry.reverse()`.

## Settings

**Settings → Company:** `grn_over_receipt_tolerance_pct` — allow over-receipt up to X% over PO qty (0 = strict).

## QC

Line-level `accepted_qty` / `rejected_qty` / `qc_status` on `GRNLine`. Only accepted qty posts to stock (via `post_grn_from_po`).
