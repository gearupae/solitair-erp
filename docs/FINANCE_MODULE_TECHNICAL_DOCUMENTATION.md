# Al Najah Fire ERP - Finance Module Technical Documentation

**Document Type:** Complete System Documentation (Based on Actual Implementation)  
**Version:** 2.0  
**Date:** January 2026  
**Compliance:** UAE VAT Law (Federal Decree-Law No. 8 of 2017), UAE Corporate Tax Law (Federal Decree-Law No. 47 of 2022), IFRS

---

## Table of Contents

1. [Overview](#1-overview)
2. [Core Accounting Architecture](#2-core-accounting-architecture)
3. [Sales Module](#3-sales-module)
4. [Purchase Module](#4-purchase-module)
5. [Payments Module](#5-payments-module)
6. [Payroll Module](#6-payroll-module)
7. [Fixed Assets Module](#7-fixed-assets-module)
8. [Inventory Module](#8-inventory-module)
9. [Projects Module](#9-projects-module)
10. [Property Management Module](#10-property-management-module)
11. [Banking Module](#11-banking-module)
12. [Journal Entries](#12-journal-entries)
13. [Opening Balances](#13-opening-balances)
14. [VAT & Corporate Tax](#14-vat--corporate-tax)
15. [Report Derivations](#15-report-derivations)
16. [Calculation Formulas](#16-calculation-formulas)
17. [Appendices](#17-appendices)

---

## 1. Overview

### 1.1 Source of Truth

The Finance module uses **double-entry accounting** with the `JournalEntry` and `JournalEntryLine` models as the **SINGLE SOURCE OF TRUTH**. 

**CRITICAL RULE:** All financial reports (Trial Balance, General Ledger, P&L, Balance Sheet, Cash Flow) derive data EXCLUSIVELY from:
- `JournalEntry` (header with status, date, reference)
- `JournalEntryLine` (individual debit/credit postings)

No operational module directly affects reports. All modules MUST create journal entries to impact the ledger.

### 1.2 Key Models

| Model | Table | Purpose |
|-------|-------|---------|
| `Account` | `finance_account` | Chart of Accounts (master data) |
| `JournalEntry` | `finance_journalentry` | Journal header (source of truth) |
| `JournalEntryLine` | `finance_journalentryline` | Debit/Credit lines (source of truth) |
| `FiscalYear` | `finance_fiscalyear` | Fiscal year management |
| `AccountingPeriod` | `finance_accountingperiod` | Monthly period controls |
| `Payment` | `finance_payment` | Payment records |
| `BankAccount` | `finance_bankaccount` | Bank account master |
| `BankStatement` | `finance_bankstatement` | Bank reconciliation |
| `AccountMapping` | `finance_accountmapping` | Account determination rules |

### 1.3 Account Types and Normal Balances

| Account Type | Normal Balance | Debit Effect | Credit Effect |
|-------------|----------------|--------------|---------------|
| **ASSET** | Debit | Increases | Decreases |
| **LIABILITY** | Credit | Decreases | Increases |
| **EQUITY** | Credit | Decreases | Increases |
| **INCOME** | Credit | Decreases | Increases |
| **EXPENSE** | Debit | Increases | Decreases |

**CRITICAL RULE:** Cash and Bank accounts are ASSETS and MUST show DEBIT balance when positive. A CREDIT balance indicates:
- Overdraft (if `overdraft_allowed = True`)
- Abnormal balance / Error (if `overdraft_allowed = False`)

### 1.4 Account Determination (SAP/Oracle Standard)

The system uses `AccountMapping` model for centralized account determination:

```python
# How accounts are retrieved
account = AccountMapping.get_account_or_default(transaction_type, fallback_code)
```

| Transaction Type | Description | Default Fallback |
|-----------------|-------------|------------------|
| `sales_invoice_receivable` | AR Account | 1200 |
| `sales_invoice_revenue` | Sales Revenue | 4000 |
| `sales_invoice_vat` | VAT Payable | 2100 |
| `vendor_bill_payable` | AP Account | 2000 |
| `vendor_bill_expense` | Default Expense | 5000 |
| `vendor_bill_vat` | VAT Recoverable | 1300 |
| `payroll_salary_expense` | Salary Expense | 5100 |
| `payroll_salary_payable` | Salary Payable | 2300 |
| `fixed_asset` | Fixed Asset | 1400 |
| `accumulated_depreciation` | Accum Depreciation | 1401 |
| `depreciation_expense` | Depreciation Expense | 5300 |
| `inventory_asset` | Inventory Asset | 1500 |
| `inventory_cogs` | Cost of Goods Sold | 5100 |
| `inventory_grn_clearing` | GRN Clearing | 2010 |
| `inventory_variance` | Stock Variance | 5200 |
| `project_expense` | Project Expense | 5000 |
| `pdc_control` | PDC Control Account | 1600 |

---

## 2. Core Accounting Architecture

### 2.1 Journal Entry Model

**File:** `apps/finance/models.py`

```python
class JournalEntry(BaseModel):
    entry_number = CharField(unique=True, editable=False)  # Auto: JNL-YYYY-NNNN
    date = DateField()                                      # Transaction date
    reference = CharField(max_length=200)                   # Source document ref
    description = TextField()
    status = CharField(choices=['draft', 'posted', 'reversed'])
    entry_type = CharField(choices=[
        'standard', 'opening', 'adjustment', 'adjusting', 'reversal', 'closing'
    ])
    source_module = CharField(choices=[
        'manual', 'sales', 'purchase', 'payment', 'bank_transfer',
        'expense_claim', 'payroll', 'inventory', 'fixed_asset',
        'project', 'pdc', 'property', 'vat', 'corporate_tax',
        'opening_balance', 'year_end', 'reversal', 'adjustment'
    ])
    source_id = PositiveIntegerField(null=True)      # ID of source document
    is_system_generated = BooleanField(default=False) # True = auto-created
    is_locked = BooleanField(default=False)           # Immutable when True
    fiscal_year = ForeignKey(FiscalYear)
    period = ForeignKey(AccountingPeriod)
    total_debit = DecimalField()
    total_credit = DecimalField()
    reversal_of = ForeignKey('self', null=True)       # For reversal entries
    posted_date = DateTimeField(null=True)
    posted_by = ForeignKey(User, null=True)
```

### 2.2 Journal Entry Line Model

```python
class JournalEntryLine(models.Model):
    journal_entry = ForeignKey(JournalEntry, related_name='lines')
    account = ForeignKey(Account)
    description = CharField(max_length=500)
    debit = DecimalField(max_digits=15, decimal_places=2, default=0.00)
    credit = DecimalField(max_digits=15, decimal_places=2, default=0.00)
    line_number = PositiveIntegerField()
```

### 2.3 Posting Logic

**Method:** `JournalEntry.post(user)`

**Validation Steps:**
1. Entry must be balanced: `total_debit == total_credit`
2. Minimum 2 lines required
3. Period must NOT be locked (`period.is_locked == False`)
4. Fiscal year must NOT be closed (`fiscal_year.is_closed == False`)
5. All accounts must be leaf accounts (no children)

**Balance Update Logic:**
```python
for line in journal.lines.all():
    account = line.account
    if account.debit_increases:  # Asset, Expense
        account.balance += line.debit - line.credit
    else:  # Liability, Equity, Income
        account.balance += line.credit - line.debit
    account.opening_balance_locked = True
    account.save()
```

### 2.4 Edit/Delete/Reversal Rules (IMMUTABILITY)

| Condition | Editable | Deletable | Reversible |
|-----------|----------|-----------|------------|
| Status = Draft + Manual Entry | ✅ YES | ✅ YES | ❌ NO |
| Status = Draft + System-Generated | ❌ NO | ❌ NO | ❌ NO |
| Status = Posted | ❌ NO | ❌ NO | ✅ YES |
| Status = Reversed | ❌ NO | ❌ NO | ❌ NO |
| Period Locked | ❌ NO | ❌ NO | ❌ NO |
| Fiscal Year Closed | ❌ NO | ❌ NO | ❌ NO |
| is_locked = True | ❌ NO | ❌ NO | ❌ NO |

**Reversal Process:**
1. Create new JournalEntry with `entry_type = 'reversal'`
2. Set `reversal_of = original_journal`
3. Swap debit/credit for each line
4. Post the reversal
5. Set original journal `status = 'reversed'`

---

## 3. Sales Module

### 3.1 Sales Invoice

#### 3.1.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created | Accounts Affected |
|--------|---------------|-----------------|-------------------|
| **Draft** | ❌ NO | ❌ NO | None |
| **Posted** | ✅ YES | ✅ YES | AR (Dr), Revenue (Cr), VAT (Cr) |
| **Sent** | ❌ NO | ❌ NO | No additional impact |
| **Partial** | ❌ NO | ❌ NO | Payment creates separate journal |
| **Paid** | ❌ NO | ❌ NO | Payment creates separate journal |
| **Overdue** | ❌ NO | ❌ NO | No ledger impact, status only |
| **Cancelled** | ✅ YES | ✅ YES | Reversal journal created |

#### 3.1.2 Posting Trigger and Journal Entry

**Trigger Event:** User clicks "Post Invoice" button  
**Method:** `Invoice.post_to_accounting(user)`

**Pre-conditions:**
- `status == 'draft'`
- `total_amount > 0`

**Journal Entry Created:**

| Line | Account | Debit | Credit | Formula |
|------|---------|-------|--------|---------|
| 1 | Accounts Receivable | `total_amount` | 0 | subtotal + vat_amount |
| 2 | Sales Revenue | 0 | `subtotal` | Sum of line item totals |
| 3 | VAT Payable | 0 | `vat_amount` | Sum of line item VAT |

**Post-conditions:**
- `invoice.status = 'posted'`
- `invoice.journal_entry = journal`

#### 3.1.3 Report Impact (Posted Invoice)

| Report | Impact |
|--------|--------|
| **Trial Balance** | AR increases (Debit side), Revenue + VAT increase (Credit side) |
| **General Ledger** | Entry visible under AR, Sales, VAT Payable accounts |
| **Profit & Loss** | Revenue recognized under Sales |
| **Balance Sheet** | AR shown as Current Asset |
| **Cash Flow Statement** | NO IMPACT (accrual, not cash) |
| **VAT Report** | Output VAT (`standard_rated_vat`) increases |
| **AR Aging** | New receivable added with due_date |

#### 3.1.4 Cancellation Behavior

**Current Implementation:** Direct reversal journal created
```python
# Reversal Entry
Dr VAT Payable           vat_amount
Dr Sales Revenue         subtotal
Cr Accounts Receivable   total_amount
```

---

### 3.2 Sales Credit Note

#### 3.2.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created |
|--------|---------------|-----------------|
| **Draft** | ❌ NO | ❌ NO |
| **Posted** | ✅ YES | ✅ YES |
| **Cancelled** | ✅ YES | ✅ YES (Reversal) |

#### 3.2.2 Journal Entry (Posted Credit Note)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Sales Returns / Revenue | `subtotal` | 0 |
| 2 | VAT Payable | `vat_amount` | 0 |
| 3 | Accounts Receivable | 0 | `total_amount` |

**Effect:** Reduces AR and Revenue, reduces VAT liability

#### 3.2.3 Report Impact

| Report | Impact |
|--------|--------|
| **Trial Balance** | AR decreases, Revenue decreases, VAT Payable decreases |
| **P&L** | Revenue reduced (Sales Returns) |
| **VAT Report** | Output VAT decreased |
| **AR Aging** | Receivable reduced or cleared |

---

## 4. Purchase Module

### 4.1 Vendor Bill

#### 4.1.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created | Accounts Affected |
|--------|---------------|-----------------|-------------------|
| **Draft** | ❌ NO | ❌ NO | None |
| **Posted** | ✅ YES | ✅ YES | Expense (Dr), VAT Recoverable (Dr), AP (Cr) |
| **Pending** | ❌ NO | ❌ NO | Status flag only |
| **Partial** | ❌ NO | ❌ NO | Payment creates separate journal |
| **Paid** | ❌ NO | ❌ NO | Payment creates separate journal |
| **Overdue** | ❌ NO | ❌ NO | Status flag only |

#### 4.1.2 Posting Trigger and Journal Entry

**Trigger Event:** User clicks "Post Bill"  
**Method:** `VendorBill.post_to_accounting(user)`

**Journal Entry Created:**

| Line | Account | Debit | Credit | Description |
|------|---------|-------|--------|-------------|
| 1 | Expense Account | `subtotal` | 0 | Expense - {bill_number} |
| 2 | VAT Recoverable | `vat_amount` | 0 | Input VAT - {bill_number} |
| 3 | Accounts Payable | 0 | `total_amount` | AP - {vendor_name} |

#### 4.1.3 Report Impact (Posted Bill)

| Report | Impact |
|--------|--------|
| **Trial Balance** | Expense increases (Dr), VAT Asset increases (Dr), AP increases (Cr) |
| **General Ledger** | Entries under Expense, VAT Recoverable, AP |
| **Profit & Loss** | Expense recognized |
| **Balance Sheet** | VAT Recoverable as Current Asset, AP as Current Liability |
| **Cash Flow Statement** | NO IMPACT (accrual) |
| **VAT Report** | Input VAT (`standard_rated_expenses`, `input_vat`) increases |
| **AP Aging** | New payable added with due_date |

---

### 4.2 Expense Claims

#### 4.2.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created |
|--------|---------------|-----------------|
| **Draft** | ❌ NO | ❌ NO |
| **Submitted** | ❌ NO | ❌ NO |
| **Approved** | ✅ YES | ✅ YES |
| **Rejected** | ❌ NO | ❌ NO |
| **Paid** | ✅ YES | ✅ YES (Payment journal) |

#### 4.2.2 Approval Journal Entry

**Trigger:** Expense claim approved  
**Method:** `ExpenseClaim.post_approval_journal(user)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Expense Account | `total_amount - total_vat` | 0 |
| 2 | VAT Recoverable | `total_vat` | 0 |
| 3 | Employee Payable | 0 | `total_amount` |

**VAT Rule:** VAT claimable ONLY if `has_receipt = True` on expense item

#### 4.2.3 Payment Journal Entry

**Trigger:** Expense claim paid  
**Method:** `ExpenseClaim.post_payment_journal(bank_account, payment_date)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Employee Payable | `total_amount` | 0 |
| 2 | Bank Account | 0 | `total_amount` |

---

### 4.3 Recurring Expenses

**Current Implementation:** Template-based system

| Action | Ledger Impact |
|--------|---------------|
| Create Template | ❌ NO |
| Generate Instance | Creates document (Invoice/Bill) |
| Post Generated Document | ✅ YES |

**Process Flow:**
1. Recurring Expense template stores schedule and amounts
2. Scheduler generates actual document (Invoice/Bill) based on `next_date`
3. Generated document follows standard posting rules

**Note:** Template itself NEVER posts to ledger. Only generated documents post.

---

## 5. Payments Module

### 5.1 Payment Received (Customer Payment)

#### 5.1.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created |
|--------|---------------|-----------------|
| **Draft** | ❌ NO | ❌ NO |
| **Confirmed** | ✅ YES | ✅ YES |
| **Reconciled** | ❌ NO | ❌ NO (Status update only) |
| **Cancelled** | ✅ YES | ✅ YES (Reversal) |

#### 5.1.2 Confirmation Journal Entry

**Trigger:** Payment confirmed  
**Method:** Created in `receive_payment` view

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Bank/Cash Account | `amount` | 0 |
| 2 | Accounts Receivable | 0 | `amount` |

#### 5.1.3 Report Impact

| Report | Impact |
|--------|--------|
| **Trial Balance** | Bank increases (Dr), AR decreases (Cr) |
| **Cash Flow Statement** | ✅ Operating Activity: Cash received from customers |
| **AR Aging** | Outstanding balance reduced |
| **Bank Ledger** | Balance increases |

#### 5.1.4 Special Scenarios

**Partial Payment:**
- `allocated_amount < amount`
- AR balance = original - payment
- Remaining AR stays in aging report

**Overpayment:**
- `unallocated_amount = amount - allocated_amount`
- Excess posted to Customer Advances (Liability)

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Bank/Cash | `amount` | 0 |
| 2 | Accounts Receivable | 0 | `allocated_amount` |
| 3 | Customer Advances | 0 | `unallocated_amount` |

---

### 5.2 Payment Made (Vendor Payment)

#### 5.2.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created |
|--------|---------------|-----------------|
| **Draft** | ❌ NO | ❌ NO |
| **Confirmed** | ✅ YES | ✅ YES |
| **Reconciled** | ❌ NO | ❌ NO |
| **Cancelled** | ✅ YES | ✅ YES (Reversal) |

#### 5.2.2 Confirmation Journal Entry

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Accounts Payable | `amount` | 0 |
| 2 | Bank/Cash Account | 0 | `amount` |

#### 5.2.3 Report Impact

| Report | Impact |
|--------|--------|
| **Trial Balance** | AP decreases (Dr), Bank decreases (Cr) |
| **Cash Flow Statement** | ✅ Operating Activity: Cash paid to suppliers |
| **AP Aging** | Outstanding balance reduced |
| **Bank Ledger** | Balance decreases |

---

## 6. Payroll Module

### 6.1 Payroll Processing

#### 6.1.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created | Accounts Affected |
|--------|---------------|-----------------|-------------------|
| **Draft** | ❌ NO | ❌ NO | None |
| **Processed** | ✅ YES | ✅ YES | Salary Expense (Dr), Salary Payable (Cr) |
| **Paid** | ✅ YES | ✅ YES | Salary Payable (Dr), Bank (Cr) |

#### 6.1.2 Processing Journal Entry

**Trigger:** Payroll processed  
**Method:** `Payroll.post_to_accounting(user)`

**Calculation:**
```python
gross_salary = basic_salary + allowances
net_salary = gross_salary - deductions
```

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Salary Expense | `gross_salary` | 0 |
| 2 | Salary Payable | 0 | `net_salary` |
| 3 | Salary Payable | 0 | `deductions` |

**Note:** Deductions credited to Salary Payable (simplified). For detailed tracking, individual deduction accounts can be used.

#### 6.1.3 Payment Journal Entry

**Trigger:** Salary paid  
**Method:** `Payroll.post_payment_journal(bank_account, payment_date)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Salary Payable | `net_salary` | 0 |
| 2 | Bank Account | 0 | `net_salary` |

#### 6.1.4 Report Impact

| Report | Impact (Processed) | Impact (Paid) |
|--------|-------------------|---------------|
| **Trial Balance** | Expense ↑ (Dr), Payable ↑ (Cr) | Payable ↓ (Dr), Bank ↓ (Cr) |
| **P&L** | Salary Expense recognized | No change |
| **Balance Sheet** | Liability (Salary Payable) created | Liability cleared, Bank reduced |
| **Cash Flow** | No impact | Operating: Cash paid to employees |

---

## 7. Fixed Assets Module

### 7.1 Asset Lifecycle

| Status | Action | Ledger Impact | Journal Created |
|--------|--------|---------------|-----------------|
| **Draft** | Create asset | ❌ NO | ❌ NO |
| **Active** | Activate/Capitalize | ✅ YES | ✅ YES |
| **Active** | Run Depreciation | ✅ YES | ✅ YES |
| **Fully Depreciated** | Book value = salvage | ❌ NO | ❌ NO |
| **Disposed** | Sell/Write-off | ✅ YES | ✅ YES |

### 7.2 Asset Activation (Capitalization)

**Trigger:** User activates draft asset  
**Method:** `FixedAsset.activate(user)`

**Journal Entry:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Fixed Asset Account | `acquisition_cost` | 0 |
| 2 | AP/Clearing Account | 0 | `acquisition_cost` |

**Report Impact:**
- Balance Sheet: Fixed Asset increases
- If linked to bill: AP balance matches

### 7.3 Depreciation Run

**Trigger:** Monthly depreciation run  
**Method:** `FixedAsset.run_depreciation(depreciation_date, user)`

**Depreciation Calculation:**

**Straight-Line Method:**
```python
depreciable_amount = acquisition_cost - salvage_value
monthly_depreciation = depreciable_amount / useful_life_months
```

**Declining Balance Method:**
```python
rate = 2 / useful_life_months  # Double declining
monthly_depreciation = book_value * rate
```

**Journal Entry:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Depreciation Expense | `depreciation_amount` | 0 |
| 2 | Accumulated Depreciation | 0 | `depreciation_amount` |

**Asset Update:**
```python
accumulated_depreciation += depreciation_amount
book_value = acquisition_cost - accumulated_depreciation
if book_value <= salvage_value:
    status = 'fully_depreciated'
```

**Report Impact:**
- P&L: Depreciation Expense recognized
- Balance Sheet: Accum Depreciation (contra asset) increases, Net Fixed Asset decreases

### 7.4 Asset Disposal

**Trigger:** Asset disposed/sold  
**Method:** `FixedAsset.dispose(disposal_date, disposal_amount, reason, user)`

**Gain/Loss Calculation:**
```python
gain_loss = disposal_amount - book_value
# If positive = Gain on Disposal
# If negative = Loss on Disposal
```

**Journal Entry:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Accumulated Depreciation | `accumulated_depreciation` | 0 |
| 2 | Bank/Receivable | `disposal_amount` | 0 |
| 3 | Loss on Disposal (if loss) | `abs(loss)` | 0 |
| 3 | Gain on Disposal (if gain) | 0 | `gain` |
| 4 | Fixed Asset Account | 0 | `acquisition_cost` |

---

## 8. Inventory Module

### 8.1 Stock Movement Types

| Movement Type | Source | Ledger Impact | COGS Impact |
|--------------|--------|---------------|-------------|
| **Stock In** | Purchase | ✅ YES | ❌ NO |
| **Stock Out** | Sales | ✅ YES | ✅ YES |
| **Adjustment (+)** | Manual | ✅ YES | ❌ NO |
| **Adjustment (-)** | Manual | ✅ YES | ❌ NO |
| **Transfer** | Warehouse move | ❌ NO | ❌ NO |

### 8.2 Stock In (Purchase Receipt)

**Trigger:** Stock movement `movement_type = 'in'` posted  
**Method:** `StockMovement.post_to_accounting(user)`

**Cost Calculation:**
```python
total_cost = unit_cost * quantity
# If unit_cost not set, uses item.purchase_price
```

**Journal Entry:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Inventory Asset | `total_cost` | 0 |
| 2 | GRN Clearing / AP | 0 | `total_cost` |

**Stock Update:**
```python
stock.quantity += quantity
```

### 8.3 Stock Out (Sales Delivery)

**Trigger:** Stock movement `movement_type = 'out'` posted

**Journal Entry:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Cost of Goods Sold | `total_cost` | 0 |
| 2 | Inventory Asset | 0 | `total_cost` |

**Stock Update:**
```python
if stock.quantity < quantity:
    raise ValidationError("Insufficient stock")
stock.quantity -= quantity
```

**Report Impact:**
- P&L: COGS recognized
- Balance Sheet: Inventory decreased

### 8.4 Stock Adjustments

**Positive Adjustment (+):**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Inventory Asset | `total_cost` | 0 |
| 2 | Stock Variance (Expense/Income) | 0 | `total_cost` |

**Negative Adjustment (-):**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Stock Variance (Expense) | `total_cost` | 0 |
| 2 | Inventory Asset | 0 | `total_cost` |

### 8.5 Stock Transfer

**Ledger Impact:** ❌ NO direct P&L impact

**Stock Update:**
```python
# Source warehouse
source_stock.quantity -= quantity
# Destination warehouse
dest_stock.quantity += quantity
```

**Note:** Transfer is balance sheet neutral (inventory moves between locations).

---

## 9. Projects Module

### 9.1 Project Expenses

#### 9.1.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created |
|--------|---------------|-----------------|
| **Draft** | ❌ NO | ❌ NO |
| **Approved** | ❌ NO | ❌ NO |
| **Posted** | ✅ YES | ✅ YES |
| **Rejected** | ❌ NO | ❌ NO |

#### 9.1.2 Posting Journal Entry

**Trigger:** Approved expense posted  
**Method:** `ProjectExpense.post_to_accounting(user)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Project Expense Account | `amount` | 0 |
| 2 | VAT Recoverable | `vat_amount` | 0 |
| 3 | AP/Clearing | 0 | `total_amount` |

**Project Update:**
```python
project.total_expenses += expense.amount
project.save()
```

### 9.2 Project Revenue

**Current Implementation:** Revenue tracked via linked Sales Invoices

```python
# Project.update_totals()
for project_invoice in self.invoices.filter(is_active=True):
    if project_invoice.invoice.status in ['posted', 'paid', 'partial']:
        total_revenue += project_invoice.invoice.total_amount
```

**Report Impact:**
- Revenue flows through Sales Invoice posting
- Project P&L: Difference between `total_revenue` and `total_expenses`

---

## 10. Property Management Module

### 10.1 PDC Cheque Lifecycle

| Status | Action | Ledger Impact | Journal Created |
|--------|--------|---------------|-----------------|
| **Received** | Accept cheque | ❌ NO | ❌ NO |
| **Deposited** | Deposit to bank | ✅ YES | ✅ YES |
| **Cleared** | Bank confirms | ✅ YES | ✅ YES |
| **Bounced** | Bank returns | ✅ YES | ✅ YES |
| **Replaced** | New cheque | ❌ NO | ❌ NO |
| **Returned** | Give back | ❌ NO | ❌ NO |

### 10.2 PDC Deposit

**Trigger:** User deposits PDC  
**Method:** `PDCCheque.deposit(bank_account, user, deposit_date)`

**Journal Entry:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | PDC Control Account (Asset) | `amount` | 0 |
| 2 | Trade Debtors (Tenant AR) | 0 | `amount` |

**CRITICAL:** PDC does NOT go to Bank. Goes to PDC Control (intermediate asset).

**Status Update:**
- `status = 'deposited'`
- `deposit_status = 'in_clearing'`

### 10.3 PDC Clearance

**Trigger:** Bank confirms clearance  
**Method:** `PDCCheque.clear(user, cleared_date, reference)`

**Journal Entry:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Bank Account | `amount` | 0 |
| 2 | PDC Control Account | 0 | `amount` |

**Cash Flow Impact:** ✅ YES - Operating activity (cash received from tenants)

### 10.4 PDC Bounce

**Trigger:** Bank returns cheque  
**Method:** `PDCCheque.bounce(user, bounce_date, reason, charges)`

**Journal Entry (Reversal):**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Trade Debtors (Tenant AR) | `amount` | 0 |
| 2 | PDC Control Account | 0 | `amount` |

**Bounce Charges (if any):**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Trade Debtors | `bounce_charges` | 0 |
| 2 | Other Income | 0 | `bounce_charges` |

### 10.5 Rent Invoices

**Current Implementation:** Uses Sales Invoice model linked to Tenant/Lease

**Posting:** Standard Sales Invoice flow with tenant-specific AR account

### 10.6 Security Deposits

**On Receipt:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Bank | `deposit_amount` | 0 |
| 2 | Security Deposit Liability | 0 | `deposit_amount` |

**On Refund:**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Security Deposit Liability | `refund_amount` | 0 |
| 2 | Bank | 0 | `refund_amount` |

---

## 11. Banking Module

### 11.1 Bank Transfer

#### 11.1.1 Status-Based Ledger Impact Matrix

| Status | Ledger Impact | Journal Created |
|--------|---------------|-----------------|
| **Draft** | ❌ NO | ❌ NO |
| **Confirmed** | ✅ YES | ✅ YES |

#### 11.1.2 Transfer Journal Entry

**Trigger:** Bank transfer confirmed  
**Method:** `BankTransfer.post_to_accounting(user)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | To Bank GL Account | `amount` | 0 |
| 2 | From Bank GL Account | 0 | `amount` |

**Cash Flow:** NO net impact (cash moves between accounts)

### 11.2 Bank Reconciliation

#### 11.2.1 Process Flow

1. Import bank statement (CSV or manual)
2. Auto-match with payments/journals
3. Manual match remaining items
4. Create adjustments for differences
5. Finalize reconciliation

#### 11.2.2 Auto-Match Logic

**Method:** `BankStatement.auto_match(date_tolerance=3)`

**Matching Criteria:**
1. Amount exact match
2. Date within ±3 days (configurable)
3. Reference (optional)

**Match Priority:**
1. Match with Payment records
2. Match with JournalEntryLine on bank GL account

#### 11.2.3 Write-offs / Adjustments

**Trigger:** Unmatched bank item requires adjustment  
**Method:** `BankStatementLine.create_adjustment(adjustment_type, expense_account, user)`

**Types:** `bank_charge`, `interest_income`, `fx_difference`, `other`

**Bank Charge (Money Out):**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Bank Charges Expense | `amount` | 0 |
| 2 | Bank GL Account | 0 | `amount` |

**Interest Income (Money In):**

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Bank GL Account | `amount` | 0 |
| 2 | Interest Income | 0 | `amount` |

### 11.3 Petty Cash

#### 11.3.1 Replenishment

**Trigger:** Petty cash replenishment posted  
**Method:** `PettyCashReplenishment.post_to_accounting(user)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Petty Cash GL | `amount` | 0 |
| 2 | Bank GL | 0 | `amount` |

---

## 12. Journal Entries

### 12.1 Manual Journal Entries

**Trigger:** User creates journal via Finance → Journal → New

| Status | Ledger Impact |
|--------|---------------|
| Draft | ❌ NO |
| Posted | ✅ YES |

**Rules:**
- Must be balanced (`total_debit == total_credit`)
- Minimum 2 lines required
- Only leaf accounts allowed
- Period must not be locked
- Fiscal year must not be closed

### 12.2 Auto-Generated Journals

**Source modules that create journals:**

| Source Module | Trigger | Journal Created |
|--------------|---------|-----------------|
| `sales` | Invoice posted | Yes |
| `purchase` | Bill posted | Yes |
| `payment` | Payment confirmed | Yes |
| `bank_transfer` | Transfer confirmed | Yes |
| `expense_claim` | Claim approved | Yes |
| `payroll` | Payroll processed | Yes |
| `inventory` | Stock movement posted | Yes |
| `fixed_asset` | Asset activated/depreciated/disposed | Yes |
| `project` | Expense posted | Yes |
| `pdc` | PDC deposited/cleared/bounced | Yes |
| `vat` | VAT adjustment | Yes |
| `corporate_tax` | Tax provision posted | Yes |
| `opening_balance` | Opening balance posted | Yes |

**Identification:** `is_system_generated = True`

### 12.3 Reversal Journals

**Trigger:** User reverses posted journal

**Process:**
1. Create new JournalEntry:
   - `entry_type = 'reversal'`
   - `reversal_of = original_journal`
   - `source_module = 'reversal'`
2. For each original line, create reverse line:
   - Swap `debit` and `credit`
3. Post the reversal
4. Set original `status = 'reversed'`

**Original journal remains immutable for audit trail.**

---

## 13. Opening Balances

### 13.1 Opening Balance Rules

**Allowed Account Types:**
- ✅ Assets
- ✅ Liabilities
- ✅ Equity
- ❌ Income (must start at zero)
- ❌ Expense (must start at zero)

**Validation (from `Account.clean()`):**
```python
if opening_balance != 0 and account_type in [INCOME, EXPENSE]:
    raise ValidationError("Opening balance not allowed for Income/Expense accounts")
```

### 13.2 System Opening Balance Entry

**Implementation:** Single system-generated journal entry

**Identification:**
- `entry_type = 'opening'`
- `source_module = 'opening_balance'`
- `is_system_generated = True`
- `reference = 'OPENING BALANCE'`

### 13.3 Opening Balance Edit Rules

| Condition | Can Edit | Reason |
|-----------|----------|--------|
| Fiscal Year Open | ✅ YES | Normal edit allowed |
| Fiscal Year Closed | ❌ NO | Locked for audit |
| Account has subsequent transactions | ❌ NO | Would affect balances |
| is_locked = True | ❌ NO | Locked journal |

**Edit Process (When Allowed):**
1. User clicks "Edit Opening Balances" button
2. System checks:
   - `fiscal_year.is_closed == False`
   - No transactions exist after opening date for modified accounts
3. If valid:
   - Modify journal entry lines directly
   - Recalculate totals
   - Log changes to audit trail
4. If invalid:
   - Show error message
   - Prevent edit

**UI/Permission Logic:**
```python
def can_edit_opening_balances():
    if not system_opening_journal:
        return False
    if system_opening_journal.fiscal_year.is_closed:
        return False
    # Check for subsequent transactions
    for line in system_opening_journal.lines.all():
        if JournalEntryLine.objects.filter(
            account=line.account,
            journal_entry__date__gt=system_opening_journal.date,
            journal_entry__status='posted'
        ).exists():
            return False  # Account has activity
    return True
```

### 13.4 Journal Entry Structure

| Line | Account Type | Debit | Credit |
|------|-------------|-------|--------|
| 1-N | Assets | balance | 0 |
| N+1-M | Liabilities | 0 | balance |
| M+1-P | Equity | 0 | balance |
| Balancing | Retained Earnings | difference | 0 (or vice versa) |

**Rule:** Total Debit MUST equal Total Credit

---

## 14. VAT & Corporate Tax

### 14.1 UAE VAT Rules

**VAT Rate:** 5% (Standard)

**VAT Calculation Formulas:**

**VAT-Exclusive:**
```python
net_amount = quantity * unit_price
vat_amount = net_amount * (vat_rate / 100)
gross_amount = net_amount + vat_amount
```

**VAT-Inclusive:**
```python
gross_amount = quantity * unit_price
net_amount = gross_amount / (1 + vat_rate / 100)
vat_amount = gross_amount - net_amount
```

### 14.2 VAT Return Model

**File:** `apps/finance/models.py`

**UAE VAT Return Boxes:**

| Box | Description | Source |
|-----|-------------|--------|
| 1 | Standard Rated Supplies | Sales invoices (5% VAT) |
| 2 | Zero Rated Supplies | Sales invoices (0% VAT) |
| 3 | Exempt Supplies | Sales invoices (exempt) |
| 9 | Standard Rated Expenses | Bills/expenses with VAT |
| 10 | Input VAT | VAT on bills/expenses |

**Net VAT Calculation:**
```python
output_vat = standard_rated_vat  # From sales
input_vat = input_vat            # From purchases
net_vat = output_vat - input_vat + adjustments
```

**If `net_vat > 0`:** Amount payable to FTA  
**If `net_vat < 0`:** Refund due from FTA

### 14.3 Corporate Tax (UAE)

**Legal Basis:** Federal Decree-Law No. 47 of 2022

**Tax Parameters:**
- Threshold: AED 375,000
- Rate: 9%

**Calculation Formula:**
```python
# Step 1: Accounting Profit
accounting_profit = revenue - expenses

# Step 2: Tax Adjustments
taxable_income = (
    accounting_profit 
    + non_deductible_expenses  # Add back: fines, penalties, non-business
    - exempt_income            # Deduct: qualifying dividends, exempt gains
    + other_adjustments        # Depreciation adjustments, provisions
)

# Step 3: Tax Calculation
if taxable_income <= 375000:
    tax_payable = 0
else:
    taxable_amount_above_threshold = taxable_income - 375000
    tax_payable = taxable_amount_above_threshold * 0.09
```

### 14.4 Corporate Tax Provision Journal

**Trigger:** Tax computation finalized  
**Method:** `CorporateTaxComputation.post_provision(user)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Corporate Tax Expense | `tax_payable` | 0 |
| 2 | Corporate Tax Payable | 0 | `tax_payable` |

### 14.5 Corporate Tax Payment Journal

**Trigger:** Tax payment made  
**Method:** `CorporateTaxComputation.post_payment(bank_account, payment_date)`

| Line | Account | Debit | Credit |
|------|---------|-------|--------|
| 1 | Corporate Tax Payable | `paid_amount` | 0 |
| 2 | Bank Account | 0 | `paid_amount` |

---

## 15. Report Derivations

### 15.1 Trial Balance

**Source:** `JournalEntryLine` aggregated by Account

**Calculation Logic:**
```python
for each account:
    # Sum all posted journal lines up to as_of_date
    total_debit = Sum(lines.debit) WHERE status='posted' AND date <= as_of_date
    total_credit = Sum(lines.credit)
    net_balance = total_debit - total_credit
    
    # Determine column based on account nature
    if account.debit_increases:  # Asset, Expense
        if net_balance >= 0:
            display_debit = net_balance
            display_credit = 0
        else:
            # ABNORMAL: Asset/Expense with credit balance
            display_debit = net_balance  # Negative in debit column
            display_credit = 0
            flag_as_abnormal = True
    else:  # Liability, Equity, Income
        if net_balance <= 0:
            display_debit = 0
            display_credit = abs(net_balance)
        else:
            # ABNORMAL: Liability/Equity/Income with debit balance
            display_debit = net_balance
            display_credit = 0
            flag_as_abnormal = True
```

**Cash/Bank Account Rule:**
- **Normal:** Positive balance = Debit
- **Overdraft:** Negative balance = Shows in parentheses, flagged as overdraft if `overdraft_allowed = True`
- **Error:** Negative balance without overdraft flag = Show warning

**Validation:**
```
Total Debit MUST equal Total Credit
```

### 15.2 General Ledger

**Source:** `JournalEntryLine` filtered by account and date range

**Structure:**
- Opening Balance (prior period totals)
- Transactions (date, reference, description, debit, credit)
- Running Balance
- Closing Balance

### 15.3 Cash Flow Statement (Direct Method)

**Source:** `JournalEntryLine` WHERE `account.is_cash_account = True`

**MUST INCLUDE:**
- Payment transactions (received/made)
- Bank statement entries (cleared)
- PDC clearances (when bank clears)

**MUST EXCLUDE:**
- Non-cash entries (depreciation, provisions)
- PDC deposits (until cleared)
- AR/AP balances
- Sales/Purchase ledger values

**Categories:**

| Category | Includes |
|----------|----------|
| **Operating** | Cash from customers, payments to suppliers/employees/taxes |
| **Investing** | Fixed asset purchases/sales, investments |
| **Financing** | Capital contributions, loan receipts/payments, drawings |

**Validation:**
```
Opening Cash + Net Cash Change = Closing Cash
```

### 15.4 Profit & Loss

**Source:** `JournalEntryLine` for Income and Expense accounts

**Structure:**
```
Revenue (Income accounts)
- Cost of Sales (COGS accounts)
= Gross Profit
- Operating Expenses (Expense accounts)
= Operating Profit
± Other Income/Expenses
= Net Profit Before Tax
- Corporate Tax
= Net Profit After Tax
```

### 15.5 Balance Sheet

**Source:** `JournalEntryLine` for Asset, Liability, Equity accounts

**Structure:**
```
ASSETS
  Current Assets
    - Cash & Bank
    - Trade Receivables (AR)
    - Inventory
    - VAT Recoverable
    - Prepaid Expenses
  Non-Current Assets
    - Fixed Assets
    - Less: Accumulated Depreciation
    - Intangible Assets

LIABILITIES
  Current Liabilities
    - Trade Payables (AP)
    - VAT Payable
    - Salary Payable
    - Corporate Tax Payable
  Non-Current Liabilities
    - Long-term Loans

EQUITY
  - Share Capital
  - Retained Earnings (Opening + P&L)
  - Current Year Profit/Loss
```

**Equation:** `Assets = Liabilities + Equity`

### 15.6 AR Aging

**Source:** `Invoice` model with payment allocation

**Aging Buckets:**
| Bucket | Condition |
|--------|-----------|
| Current | Not due (due_date >= today) |
| 1-30 days | due_date between today-30 and today-1 |
| 31-60 days | due_date between today-60 and today-31 |
| 61-90 days | due_date between today-90 and today-61 |
| 90+ days | due_date < today-90 |

**Calculation:**
```python
outstanding = invoice.total_amount - invoice.paid_amount
days_overdue = (today - invoice.due_date).days if today > invoice.due_date else 0
```

### 15.7 AP Aging

**Source:** `VendorBill` model with payment allocation

**Same aging bucket structure as AR**

---

## 16. Calculation Formulas

### 16.1 VAT Calculations

**VAT-Exclusive (Standard):**
```
Net Amount = Quantity × Unit Price
VAT Amount = Net Amount × (VAT Rate / 100)
Gross Amount = Net Amount + VAT Amount
```

**VAT-Inclusive (Back-Calculate):**
```
Gross Amount = Quantity × Unit Price
Net Amount = Gross Amount / (1 + VAT Rate / 100)
VAT Amount = Gross Amount - Net Amount
```

### 16.2 AR Balance

```
AR Balance = Σ(Invoice Total Amounts) - Σ(Payments Received) - Σ(Credit Notes)
```

### 16.3 AP Balance

```
AP Balance = Σ(Bill Total Amounts) - Σ(Payments Made) - Σ(Debit Notes)
```

### 16.4 Inventory Valuation

**Current Implementation:** Weighted Average Cost

```
Average Cost = Total Inventory Value / Total Quantity
COGS = Quantity Sold × Average Cost
```

### 16.5 Depreciation Formulas

**Straight-Line:**
```
Annual Depreciation = (Acquisition Cost - Salvage Value) / Useful Life Years
Monthly Depreciation = Annual Depreciation / 12
```

**Double Declining Balance:**
```
Depreciation Rate = (2 / Useful Life Years)
Annual Depreciation = Book Value × Depreciation Rate
Monthly Depreciation = Annual Depreciation / 12
```

### 16.6 Project Profitability

```
Project Profit = Total Revenue - Total Expenses
Profit Margin % = (Project Profit / Total Revenue) × 100
Budget Utilization % = (Total Expenses / Budget) × 100
```

### 16.7 Corporate Tax

```
Accounting Profit = Total Revenue - Total Expenses
Taxable Income = Accounting Profit + Non-Deductible Expenses - Exempt Income
Tax Payable = MAX(0, Taxable Income - 375,000) × 9%
```

### 16.8 Retained Earnings

```
Closing Retained Earnings = 
    Opening Retained Earnings 
    + Net Profit for Period 
    - Dividends Declared
```

---

## 17. Appendices

### 17.1 Account Mapping Reference

| Transaction Type | Module | Debit Account | Credit Account |
|-----------------|--------|---------------|----------------|
| `sales_invoice_receivable` | Sales | AR (1200) | - |
| `sales_invoice_revenue` | Sales | - | Sales (4000) |
| `sales_invoice_vat` | Sales | - | VAT Payable (2100) |
| `vendor_bill_payable` | Purchase | - | AP (2000) |
| `vendor_bill_expense` | Purchase | Expense (5000) | - |
| `vendor_bill_vat` | Purchase | VAT Recoverable (1300) | - |
| `payroll_salary_expense` | Payroll | Salary Expense (5100) | - |
| `payroll_salary_payable` | Payroll | - | Salary Payable (2300) |
| `fixed_asset` | Assets | Fixed Asset (1400) | - |
| `accumulated_depreciation` | Assets | - | Accum Depr (1401) |
| `depreciation_expense` | Assets | Depr Expense (5300) | - |
| `inventory_asset` | Inventory | Inventory (1500) | - |
| `inventory_cogs` | Inventory | COGS (5100) | - |
| `inventory_grn_clearing` | Inventory | - | GRN Clearing (2010) |
| `inventory_variance` | Inventory | Stock Variance (5200) | - |
| `pdc_control` | Property | PDC Control (1600) | - |

### 17.2 Status Flow Diagrams

**Sales Invoice:**
```
Draft → Posted → [Sent] → [Partial] → Paid
                       ↓
                   Cancelled (Reversal)
```

**Vendor Bill:**
```
Draft → Posted → [Pending] → [Partial] → Paid
                          ↓
                       Overdue
```

**PDC Cheque:**
```
Received → Deposited → Cleared
                    ↓
                 Bounced → [Replaced]
                        → [Returned]
```

**Journal Entry:**
```
Draft → Posted → Reversed
```

**Payroll:**
```
Draft → Processed → Paid
```

**Fixed Asset:**
```
Draft → Active → [Depreciated Monthly] → Fully Depreciated
              ↓
           Disposed
```

### 17.3 Complete Ledger Impact Summary

| Document | Draft | Approved | Posted | Paid | Cancelled |
|----------|-------|----------|--------|------|-----------|
| Sales Invoice | ❌ | N/A | ✅ | ❌ | ✅ Reversal |
| Credit Note | ❌ | N/A | ✅ | N/A | ✅ Reversal |
| Vendor Bill | ❌ | N/A | ✅ | ❌ | ✅ Reversal |
| Expense Claim | ❌ | ✅ | N/A | ✅ | ❌ |
| Payment Received | ❌ | N/A | N/A | N/A (Confirmed=✅) | ✅ Reversal |
| Payment Made | ❌ | N/A | N/A | N/A (Confirmed=✅) | ✅ Reversal |
| Payroll | ❌ | N/A | N/A | N/A (Processed=✅, Paid=✅) | ❌ |
| Fixed Asset | ❌ | N/A | N/A | N/A (Activated=✅) | ❌ |
| Depreciation | N/A | N/A | N/A | N/A (Run=✅) | ❌ |
| Stock In | ❌ | N/A | ✅ | N/A | ❌ |
| Stock Out | ❌ | N/A | ✅ | N/A | ❌ |
| PDC Deposit | N/A | N/A | N/A | N/A (Deposited=✅) | ❌ |
| PDC Clearance | N/A | N/A | N/A | N/A (Cleared=✅) | ❌ |
| PDC Bounce | N/A | N/A | N/A | N/A (Bounced=✅) | ❌ |
| Bank Transfer | ❌ | N/A | N/A | N/A (Confirmed=✅) | ❌ |
| Manual Journal | ❌ | N/A | ✅ | N/A | Delete (Draft) / Reverse (Posted) |
| Opening Balance | ❌ | N/A | ✅ | N/A | ❌ (Locked) |

### 17.4 Audit Trail

**Model:** `AuditLog` (in settings_app)

**Logged Actions:**
- Create, Update, Delete on all finance records
- Post, Reverse, Approve actions
- Bank reconciliation matches
- Opening balance edits

**Captured Data:**
| Field | Description |
|-------|-------------|
| `user` | User who performed action |
| `timestamp` | Date/time of action |
| `action` | create, update, delete, post, reverse, approve |
| `entity_type` | Model name (Invoice, Journal, Payment, etc.) |
| `entity_id` | Record ID |
| `changes` | Before/after values (JSON) |
| `ip_address` | Client IP address |

---

**Document End**

*This document reflects the actual implementation as of January 2026. It is intended for use by auditors, developers, and finance users to understand exact ledger behavior.*

**Revision History:**
| Version | Date | Changes |
|---------|------|---------|
| 1.0 | Jan 2026 | Initial documentation |
| 2.0 | Jan 2026 | Expanded with ledger impact matrices, calculation formulas, opening balance edit rules, cash account handling |
