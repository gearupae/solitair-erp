#!/usr/bin/env python3
"""Capture Solitair ERP user-guide screenshots from the live site.

Usage:
  export ERP_DOC_BASE_URL=https://solitair.telldb.com
  export ERP_DOC_USER=solitair
  export ERP_DOC_PASSWORD='your-password'
  python docs/user-guide/capture_screenshots.py
"""
from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ERP_DOC_BASE_URL", "https://solitair.telldb.com")
USERNAME = os.environ.get("ERP_DOC_USER", "solitair")
PASSWORD = os.environ.get("ERP_DOC_PASSWORD", "")
OUT = Path(__file__).resolve().parent / "screenshots"

PAGES = [
    ("01-dashboard", "/"),
    ("02-purchase-dashboard", "/purchase/dashboard/"),
    ("03-purchase-vendors", "/purchase/vendors/"),
    ("04-purchase-requests", "/purchase/requests/"),
    ("05-service-requests", "/service-request/"),
    ("06-purchase-orders", "/purchase/orders/"),
    ("07-goods-receipt", "/purchase/grn/"),
    ("08-rfq", "/purchase/rfq/"),
    ("09-vendor-bills", "/purchase/bills/"),
    ("10-expense-claims", "/purchase/expense-claims/"),
    ("11-recurring-expenses", "/purchase/recurring-expenses/"),
    ("12-hr-employees", "/hr/employees/"),
    ("13-hr-departments", "/hr/departments/"),
    ("14-hr-designations", "/hr/designations/"),
    ("15-inventory-items", "/inventory/items/"),
    ("16-inventory-groups", "/inventory/groups/"),
    ("17-inventory-categories", "/inventory/categories/"),
    ("18-inventory-warehouses", "/inventory/warehouses/"),
    ("19-inventory-stock", "/inventory/stock/"),
    ("20-inventory-movements", "/inventory/movements/"),
    ("21-inventory-transfers", "/inventory/transfers/"),
    ("22-inventory-adjustment", "/inventory/stock/adjustment/"),
    ("23-stock-take", "/stock-take/"),
    ("24-inventory-reports", "/inventory/consumables/reports/inventory/"),
    ("25-settings-users", "/settings/users/"),
    ("26-settings-roles", "/settings/roles/"),
    ("27-settings-company", "/settings/company/"),
    ("28-settings-approval", "/settings/approval-configuration/"),
    ("29-account-modules", "/account/modules/"),
    ("30-account-profile", "/account/profile/"),
]


def main() -> None:
    if not PASSWORD:
        raise SystemExit("Set ERP_DOC_PASSWORD before running.")

    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        page.goto(f"{BASE}/login/", wait_until="networkidle", timeout=60000)
        page.fill('input[name="username"]', USERNAME)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=60000)

        if "/login" in page.url:
            raise SystemExit(f"Login failed — still at {page.url}")

        for name, path in PAGES:
            page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print(f"OK {name}")

        browser.close()


if __name__ == "__main__":
    main()
