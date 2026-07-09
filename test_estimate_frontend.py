#!/usr/bin/env python3
"""
Playwright frontend tests for the Gearup ERP Estimate form.

Credentials: set ERP_TEST_USER and ERP_TEST_PASSWORD env vars, or edit CONFIG below.

Run:
  source venv/bin/activate
  export ERP_TEST_USER=youruser ERP_TEST_PASSWORD=yourpass
  python test_estimate_frontend.py

Outputs screenshots and PDF under ./test_output/
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------------------------
# Configuration — override via environment variables when possible
# ---------------------------------------------------------------------------
CONFIG = {
    'base_url': os.environ.get('ERP_TEST_BASE_URL', 'http://localhost:7001'),
    'username': os.environ.get('ERP_TEST_USER', ''),
    'password': os.environ.get('ERP_TEST_PASSWORD', ''),
    'slow_mo': int(os.environ.get('ERP_TEST_SLOW_MO', '300')),
    'headless': os.environ.get('ERP_TEST_HEADLESS', '0') == '1',
}

OUTPUT_DIR = Path(__file__).resolve().parent / 'test_output'
SUMMARY_ROWS: list[tuple[str, str, str]] = []


def record(test_name: str, field: str, value: str) -> None:
    SUMMARY_ROWS.append((test_name, field, value))
    print(f'  [{test_name}] {field}: {value}')


def require_credentials() -> None:
    if not CONFIG['username'] or not CONFIG['password']:
        print(
            '\nERROR: Set login credentials before running.\n'
            '  export ERP_TEST_USER=your_username\n'
            '  export ERP_TEST_PASSWORD=your_password\n'
            'Or edit CONFIG at the top of test_estimate_frontend.py\n'
        )
        sys.exit(1)


def url(path: str) -> str:
    base = CONFIG['base_url'].rstrip('/')
    if not path.startswith('/'):
        path = '/' + path
    return base + path


def login(page) -> None:
    page.goto(url('/login/'))
    page.fill('input[name="username"]', CONFIG['username'])
    page.fill('input[name="password"]', CONFIG['password'])
    page.click('button[type="submit"]')
    page.wait_for_load_state('networkidle')
    if '/login/' in page.url:
        raise RuntimeError('Login failed — still on login page. Check ERP_TEST_USER / ERP_TEST_PASSWORD.')


def screenshot(page, name: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / name
    page.screenshot(path=str(path), full_page=True)
    print(f'  screenshot -> {path}')
    return path


def wait_recalc(page, ms: int = 600) -> None:
    page.wait_for_timeout(ms)


def nth_visible_row(page, index: int):
    return page.locator('#itemsBody tr.item-row:not([style*="display: none"])').nth(index)


def select_inventory(page, row, item_name: str) -> None:
    """Select inventory via Select2 dropdown."""
    cell = row.locator('.items-col-inventory')
    cell.locator('.select2-container').click()
    search = page.locator('.estimate-inventory-select2-dropdown input.select2-search__field')
    search.wait_for(state='visible', timeout=5000)
    search.fill(item_name)
    page.locator('.select2-results__option').filter(has_text=item_name).first.click()
    wait_recalc(page, 900)


def fill_line_inputs(page, row, *, qty=None, unit_cost=None, install_cost=None,
                     profit_type=None, selling_cost=None, install_selling_cost=None,
                     tax_label=None, group_name=None, group_mult=None) -> None:
    if group_name is not None:
        row.locator('.item-group-name').fill(group_name)
        row.locator('.item-group-name').blur()
        wait_recalc(page)
    if group_mult is not None:
        mult = row.locator('.item-group-qty-mult')
        if mult.is_visible():
            mult.fill(str(group_mult))
            mult.blur()
            wait_recalc(page)
    if qty is not None:
        q = row.locator('.item-qty')
        q.fill(str(qty))
        q.blur()
        wait_recalc(page)
    if unit_cost is not None:
        bp = row.locator('.item-base-price')
        bp.fill(str(unit_cost))
        bp.blur()
        wait_recalc(page)
    if install_cost is not None:
        ic = row.locator('.item-installation-cost')
        ic.fill(str(install_cost))
        ic.blur()
        wait_recalc(page)
    if profit_type is not None:
        row.locator('.item-profit-type').select_option(value=profit_type)
        wait_recalc(page)
    if selling_cost is not None:
        sc = row.locator('.item-selling-cost')
        sc.fill(str(selling_cost))
        sc.blur()
        wait_recalc(page)
    if install_selling_cost is not None:
        isc = row.locator('.item-installation-selling-cost')
        isc.fill(str(install_selling_cost))
        isc.blur()
        wait_recalc(page)
    if tax_label is not None:
        tax_sel = row.locator('.item-tax-code')
        options = tax_sel.locator('option')
        count = options.count()
        matched = False
        for i in range(count):
            text = options.nth(i).inner_text()
            if tax_label.lower() in text.lower():
                tax_sel.select_option(label=text)
                matched = True
                break
        if not matched:
            raise RuntimeError(f'Tax code matching "{tax_label}" not found on row.')
        wait_recalc(page)


def read_line_computed(row) -> dict[str, str]:
    def txt(sel: str) -> str:
        loc = row.locator(sel)
        if loc.count() == 0:
            return ''
        if sel.endswith('input') or '.item-' in sel:
            try:
                return loc.input_value()
            except Exception:
                return loc.inner_text().strip()
        return loc.inner_text().strip()

    net_cost = txt('.row-net-cost')
    net_install = txt('.row-net-install-total')
    return {
        'qty_displayed': txt('.item-qty'),
        'net_cost': net_cost,
        'net_install_cost': net_install,
        'oh_indicator': txt('.row-oh-indicator'),
        'oh_amount': txt('.row-oh-amount'),
        'total_cost_plus_oh': txt('.row-total-cost-oh'),
        'profit_value': txt('.item-profit-value'),
        'install_profit_value': txt('.item-installation-profit-value'),
        'install_net_selling': txt('.row-install-net-selling'),
        'total_selling': txt('.row-total-selling'),
        'net_excl_vat': txt('.row-net'),
        'gross_incl_vat': txt('.row-gross'),
    }


def print_line_values(test_name: str, line_no: int, values: dict[str, str]) -> None:
    print(f'\n  --- Line {line_no} computed values ({test_name}) ---')
    for key, val in values.items():
        record(test_name, f'line{line_no}_{key}', val)


def read_footer(page) -> dict[str, str]:
    ids = {
        'total_product_cost': 'footerTotalProductCost',
        'total_installation': 'footerTotalInstallation',
        'total_overhead': 'footerTotalOverhead',
        'total_profit': 'footerTotalProfit',
        'total_profit_pct': 'footerTotalProfitPct',
        'subtotal_excl_vat': 'subtotal',
        'vat': 'vatTotal',
        'grand_total': 'grandTotal',
    }
    out = {}
    for key, el_id in ids.items():
        loc = page.locator(f'#{el_id}')
        out[key] = loc.inner_text().strip() if loc.count() else ''
    disc_row = page.locator('#discountExclRow')
    if disc_row.count() and 'd-none' not in (disc_row.get_attribute('class') or ''):
        out['discount_excl'] = page.locator('#discountDisplayExcl').inner_text().strip()
    else:
        out['discount_excl'] = '(none)'
    return out


def print_footer_values(test_name: str, footer: dict[str, str]) -> None:
    print(f'\n  --- Footer ({test_name}) ---')
    for key, val in footer.items():
        record(test_name, key, val)


def ensure_customer(page, company_name: str = 'TEST CUSTOMER') -> None:
    page.goto(url('/sales/estimates/create/'))
    page.wait_for_selector('#estimateForm')
    sel = page.locator('#id_customer')
    options = sel.locator('option')
    for i in range(options.count()):
        if company_name.lower() in options.nth(i).inner_text().lower():
            sel.select_option(index=i)
            return

    page.goto(url('/crm/customers/'))
    page.wait_for_load_state('networkidle')
    page.locator('button[onclick="toggleInlineForm(\'customerForm\')"]').first.click()
    form = page.locator('#customerForm')
    form.wait_for(state='visible')
    form.locator('input[name="company"]').fill(company_name)
    form.locator('input[name="phone"]').fill('+971500000000')
    assigned = form.locator('select[name="assigned_salesperson"]')
    if assigned.locator('option').count() > 1:
        assigned.select_option(index=1)
    form.locator('select[name="business_segment"]').select_option(value='b2b')
    form.locator('#createCustomerForm button[type="submit"]').click()
    page.wait_for_load_state('networkidle')
    page.goto(url('/sales/estimates/create/'))
    page.wait_for_selector('#estimateForm')
    sel = page.locator('#id_customer')
    for i in range(sel.locator('option').count()):
        if company_name.lower() in sel.locator('option').nth(i).inner_text().lower():
            sel.select_option(index=i)
            return
    raise RuntimeError(f'Customer {company_name!r} was not found after creation.')


def create_inventory_item(page, name: str, item_type: str) -> None:
    """Create item via UI; skip if an active item with the same name already exists."""
    page.goto(url('/inventory/items/'))
    page.wait_for_load_state('networkidle')
    if page.locator('table tbody tr').filter(has_text=name).count():
        record('setup', f'{name}_already_exists', 'skipped create')
        return
    page.goto(url('/inventory/items/create/'))
    page.fill('#id_name', name)
    page.select_option('#id_item_type', item_type)
    wait_recalc(page, 400)
    no_oh = page.locator('#id_no_overhead')
    record('setup', f'{name}_no_overhead_checked', str(no_oh.is_checked()))
    if name == 'TEST SERVICE':
        assert no_oh.is_checked(), 'Expected "No overhead calculation" to auto-check when type=Service'
        screenshot(page, 'setup_service_item.png')
    elif name == 'TEST PRODUCT':
        assert not no_oh.is_checked(), 'Expected product item to have no_overhead unchecked'
    page.click('button[type="submit"]')
    page.wait_for_load_state('networkidle')


def setup_inventory_items(page) -> None:
    print('\n=== SETUP A — TEST SERVICE inventory item ===')
    create_inventory_item(page, 'TEST SERVICE', 'service')
    print('\n=== SETUP B — TEST PRODUCT inventory item ===')
    create_inventory_item(page, 'TEST PRODUCT', 'product')


def save_estimate(page) -> None:
    page.locator('#estimateForm button[type="submit"]').click()
    page.wait_for_load_state('networkidle')


def find_estimate_pk_for_customer(page, customer_name: str = 'TEST CUSTOMER') -> int:
    page.goto(url('/sales/estimates/'))
    page.wait_for_load_state('networkidle')
    row = page.locator('table tbody tr').filter(has_text=customer_name).first
    row.wait_for(state='visible', timeout=15000)
    link = row.locator('a[href*="/sales/estimates/"]').first
    href = link.get_attribute('href') or ''
    m = re.search(r'/estimates/(\d+)/', href)
    if not m:
        edit = row.locator('a[href*="/edit/"]').first
        href = edit.get_attribute('href') or ''
        m = re.search(r'/estimates/(\d+)/edit/', href)
    if not m:
        raise RuntimeError(f'Could not find estimate pk for customer {customer_name!r}')
    return int(m.group(1))


def goto_estimate_edit(page, pk: int) -> None:
    page.goto(url(f'/sales/estimates/{pk}/edit/'))
    page.wait_for_selector('#estimateForm')
    page.wait_for_selector('#itemsBody tr.item-row')
    wait_recalc(page, 1200)


def add_line(page) -> None:
    page.locator('button', has_text='Add line').click()
    wait_recalc(page, 500)


def delete_row(page, row_index: int) -> None:
    row = nth_visible_row(page, row_index)
    row.locator('button.btn-outline-danger').click()
    wait_recalc(page, 500)


def run_tests(page) -> int:
    setup_inventory_items(page)

    print('\n=== TEST 1 — Basic product line ===')
    ensure_customer(page)
    page.fill('#id_overhead_percent', '10')
    page.locator('#id_customer').select_option(label=re.compile('TEST CUSTOMER', re.I))

    row1 = nth_visible_row(page, 0)
    select_inventory(page, row1, 'TEST PRODUCT')
    fill_line_inputs(
        page, row1,
        qty=10,
        unit_cost=100,
        install_cost=80,
        profit_type='amount',
        selling_cost=150,
        install_selling_cost=120,
        tax_label='5%',
    )
    vals1 = read_line_computed(row1)
    print_line_values('test1', 1, vals1)
    screenshot(page, 'test1_line.png')
    page.locator('#itemsTable tfoot').scroll_into_view_if_needed()
    footer1 = read_footer(page)
    print_footer_values('test1', footer1)
    screenshot(page, 'test1_footer.png')

    save_estimate(page)
    estimate_pk = find_estimate_pk_for_customer(page)
    record('test1', 'estimate_pk', str(estimate_pk))
    goto_estimate_edit(page, estimate_pk)
    row1_saved = nth_visible_row(page, 0)
    vals1_saved = read_line_computed(row1_saved)
    print_line_values('test1_saved', 1, vals1_saved)
    screenshot(page, 'test1_saved.png')

    print('\n=== TEST 2 — Service item, no overhead ===')
    add_line(page)
    row2 = nth_visible_row(page, 1)
    select_inventory(page, row2, 'TEST SERVICE')
    oh_indicator = row2.locator('.row-oh-indicator').inner_text().strip()
    record('test2', 'oh_indicator_after_service_select', oh_indicator)
    assert oh_indicator == 'No OH', f'Expected "No OH" indicator, got {oh_indicator!r}'
    fill_line_inputs(
        page, row2,
        qty=2,
        unit_cost=500,
        profit_type='amount',
        selling_cost=600,
        install_cost=0,
        tax_label='5%',
    )
    vals2 = read_line_computed(row2)
    print_line_values('test2', 2, vals2)
    screenshot(page, 'test2_line.png')

    print('\n=== TEST 3 — OH indicator persistence (automatic; no manual toggle) ===')
    print('  NOTE: Apply OH checkbox was replaced by automatic read-only OH indicator (Yes / No OH).')
    save_estimate(page)
    goto_estimate_edit(page, estimate_pk)
    row2_reopened = nth_visible_row(page, 1)
    oh_reopened = row2_reopened.locator('.row-oh-indicator').inner_text().strip()
    record('test3', 'oh_indicator_after_reopen', oh_reopened)
    assert oh_reopened == 'No OH', f'Expected persisted "No OH", got {oh_reopened!r}'
    vals2_reopened = read_line_computed(row2_reopened)
    print_line_values('test3_reopened', 2, vals2_reopened)
    screenshot(page, 'test3_reopened.png')

    print('\n=== TEST 4 — Percent profit + Group × ===')
    add_line(page)
    row3 = nth_visible_row(page, 2)
    fill_line_inputs(
        page, row3,
        group_name='FA',
        group_mult=2,
        qty=5,
        unit_cost=200,
        profit_type='percent',
        selling_cost=300,
        tax_label='5%',
    )
    vals4a = read_line_computed(row3)
    print_line_values('test4_groupx2', 3, vals4a)
    record('test4', 'line3_qty_displayed', vals4a['qty_displayed'])

    fill_line_inputs(page, row3, group_mult=3)
    vals4b = read_line_computed(row3)
    print_line_values('test4_groupx3', 3, vals4b)
    record('test4', 'line3_qty_after_mult3', vals4b['qty_displayed'])
    screenshot(page, 'test4_groupx.png')
    delete_row(page, 2)

    print('\n=== TEST 5 — Footer + discount ===')
    footer5a = read_footer(page)
    print_footer_values('test5_no_discount', footer5a)
    screenshot(page, 'test5_footer_nodiscount.png')

    page.select_option('[name="discount_type"]', 'percent')
    page.fill('[name="discount_value"]', '10')
    page.locator('[name="discount_value"]').blur()
    wait_recalc(page, 800)
    footer5b = read_footer(page)
    print_footer_values('test5_with_discount', footer5b)
    screenshot(page, 'test5_footer_discount.png')

    page.select_option('[name="discount_type"]', 'none')
    page.fill('[name="discount_value"]', '0')
    page.locator('[name="discount_value"]').blur()
    wait_recalc(page)
    save_estimate(page)

    print('\n=== TEST 6 — Frozen columns + live OH% ===')
    goto_estimate_edit(page, estimate_pk)
    wrap = page.locator('.line-items-table-wrap')
    wrap.evaluate('el => { el.scrollLeft = el.scrollWidth; }')
    wait_recalc(page, 400)
    frozen_visible = page.locator('th.items-col-frozen-1').is_visible()
    inventory_frozen_visible = page.locator('th.items-col-frozen-3').is_visible()
    brand_header = page.locator('th.items-col-brand')
    record('test6', 'group_header_visible_after_scroll', str(frozen_visible))
    record('test6', 'inventory_header_visible_after_scroll', str(inventory_frozen_visible))
    record('test6', 'brand_header_exists', str(brand_header.count() > 0))
    screenshot(page, 'test6_frozen_scroll.png')

    row1_live = nth_visible_row(page, 0)
    oh_before = row1_live.locator('.row-oh-amount').inner_text().strip()
    record('test6', 'line1_oh_at_10pct', oh_before)
    page.fill('#id_overhead_percent', '15')
    page.locator('#id_overhead_percent').blur()
    wait_recalc(page, 900)
    oh_after = row1_live.locator('.row-oh-amount').inner_text().strip()
    record('test6', 'line1_oh_at_15pct', oh_after)
    page.fill('#id_overhead_percent', '10')
    page.locator('#id_overhead_percent').blur()
    wait_recalc(page)
    save_estimate(page)

    print('\n=== TEST 7 — Quotation PDF ===')
    page.goto(url(f'/sales/estimates/{estimate_pk}/pdf/'))
    page.wait_for_load_state('networkidle')
    grand_total = ''
    grand_loc = page.locator('.totals-row.total .totals-value').last
    if grand_loc.count():
        grand_total = grand_loc.inner_text().strip()
    line1_rate = ''
    rate_cells = page.locator('table tbody tr td.text-right')
    if rate_cells.count():
        line1_rate = rate_cells.first.inner_text().strip()
    record('test7', 'pdf_line1_rate_html_preview', line1_rate)
    record('test7', 'pdf_grand_total_html_preview', grand_total)

    pdf_path = OUTPUT_DIR / 'test7_quotation.pdf'
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with page.expect_download(timeout=30000) as dl_info:
            page.goto(url(f'/sales/estimates/{estimate_pk}/pdf/download/'))
        download = dl_info.value
        download.save_as(str(pdf_path))
        print(f'  PDF saved -> {pdf_path}')
        record('test7', 'pdf_file', str(pdf_path))
    except PlaywrightTimeout:
        print('  PDF download timed out — HTML preview values recorded above.')
        record('test7', 'pdf_download', 'timeout')

    return estimate_pk


def print_summary_table() -> None:
    print('\n' + '=' * 72)
    print('SUMMARY — test name | field | system value')
    print('=' * 72)
    col_w = [28, 32, 20]
    print(f"{'test name':<{col_w[0]}} | {'field':<{col_w[1]}} | system value")
    print('-' * 72)
    for test_name, field, value in SUMMARY_ROWS:
        print(f'{test_name:<{col_w[0]}} | {field:<{col_w[1]}} | {value}')
    print('=' * 72)


def main() -> None:
    require_credentials()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=CONFIG['headless'],
            slow_mo=CONFIG['slow_mo'],
        )
        context = browser.new_context(viewport={'width': 1600, 'height': 1000})
        page = context.new_page()
        page.set_default_timeout(30000)

        try:
            print(f"Logging in to {CONFIG['base_url']} as {CONFIG['username']} ...")
            login(page)
            run_tests(page)
        finally:
            print_summary_table()
            browser.close()


if __name__ == '__main__':
    main()
