# 📘 Finance Module Documentation

## Overview

The Finance Module is a comprehensive, **UAE VAT & Corporate Tax compliant** accounting system built following **SAP/Oracle enterprise standards**. It supports double-entry bookkeeping, IFRS-based financial reporting, and full audit trail capabilities.

---

## 🏗️ Module Architecture

```
Finance Module
├── Chart of Accounts
├── Fiscal Years & Periods
├── Journal Entries
├── Payments
├── Banking
│   ├── Bank Accounts
│   ├── Bank Transfers
│   ├── Bank Statements
│   └── Bank Reconciliation
├── Expense Claims
├── Budgets
├── VAT Returns (UAE)
├── Tax Codes
├── Opening Balances
├── Write-Offs / Adjustments
├── Exchange Rates
├── Account Mapping (SAP/Oracle Style)
├── Accounting Settings
└── Reports
```

---

## 📋 Features

### 1. Chart of Accounts
**URL**: `/finance/accounts/`

| Feature | Description |
|---------|-------------|
| Hierarchical Structure | Parent-child account relationships |
| Account Types | Asset, Liability, Equity, Income, Expense |
| System Accounts | Protected accounts that cannot be deleted |
| Balance Tracking | Real-time balance updates |
| Opening Balance | Lock after first posting |

**Account Types:**
- `asset` - Assets (Debit increases)
- `liability` - Liabilities (Credit increases)
- `equity` - Equity (Credit increases)
- `income` - Income/Revenue (Credit increases)
- `expense` - Expenses (Debit increases)

---

### 2. Fiscal Years & Periods
**URLs**: 
- `/finance/fiscal-years/`
- `/finance/periods/`

| Feature | Description |
|---------|-------------|
| Fiscal Year Management | Create and manage accounting years |
| Period Control | Monthly/quarterly periods |
| Period Locking | Lock periods to prevent changes |
| Year-End Close | Close fiscal year and carry forward balances |

**Period Statuses:**
- `open` - Transactions allowed
- `locked` - No new transactions (audit safe)
- `closed` - Year-end closed

---

### 3. Journal Entries
**URL**: `/finance/journal/`

| Feature | Description |
|---------|-------------|
| Manual Entries | Create manual journal entries |
| Auto-Generated | From invoices, bills, payments |
| Multi-line Support | Unlimited debit/credit lines |
| Balanced Validation | Debit must equal Credit |
| Posting Control | Draft → Posted workflow |
| Reversal | Reverse posted entries |

**Entry Types:**
- `standard` - Regular journal entry
- `adjusting` - Period-end adjustments
- `closing` - Year-end closing entries
- `opening` - Opening balance entries
- `reversal` - Reversal of existing entry

**Source Modules:**
- Manual, Sales, Purchase, Payment, Bank Transfer, Expense Claim, VAT Return, Corporate Tax, Opening Balance, Reversal

---

### 4. Payments
**URL**: `/finance/payments/`

| Feature | Description |
|---------|-------------|
| Payment Received | Customer payments (AR clearing) |
| Payment Made | Vendor payments (AP clearing) |
| Multiple Methods | Bank, Cash, Cheque, Card |
| Auto Journal | Creates clearing journal entry |
| Allocation | Track allocated vs unallocated |
| Cancellation | Cancel with reversal entry |

**Payment Methods:**
- `bank` - Bank Transfer
- `cash` - Cash
- `cheque` - Cheque
- `card` - Credit/Debit Card

---

### 5. Banking

#### 5.1 Bank Accounts
**URL**: `/finance/bank-accounts/`

| Feature | Description |
|---------|-------------|
| Multiple Accounts | Manage multiple bank accounts |
| GL Linking | Link to Chart of Accounts |
| Currency | Multi-currency support |
| Balance Tracking | Current balance display |

#### 5.2 Bank Transfers
**URL**: `/finance/bank-transfers/`

| Feature | Description |
|---------|-------------|
| Inter-bank Transfer | Transfer between accounts |
| Auto Journal | Creates balanced journal entry |
| Confirmation | Draft → Confirmed workflow |

#### 5.3 Bank Statements
**URL**: `/finance/bank-statements/`

| Feature | Description |
|---------|-------------|
| Statement Import | Import bank statements |
| Manual Entry | Add lines manually |
| Auto-Matching | Automatic transaction matching |
| Manual Matching | Match specific transactions |
| Adjustments | Create adjustment entries |
| Finalization | Lock completed statements |

#### 5.4 Bank Reconciliation
**URL**: `/finance/reconciliations/`

| Feature | Description |
|---------|-------------|
| Period-based | Reconcile by period |
| GL vs Bank | Compare GL balance to bank |
| Difference Analysis | Track reconciling items |
| Approval Workflow | Complete → Approved |

---

### 6. Expense Claims (Legacy)
**URL**: `/finance/expense-claims/`

> **Note**: Primary expense claims moved to Purchase module. This is for backward compatibility.

| Feature | Description |
|---------|-------------|
| Employee Claims | Employee expense reimbursement |
| VAT Recovery | Claim VAT with valid receipts |
| Approval Workflow | Submit → Approve → Pay |
| Journal Posting | Auto-post on approval |

---

### 7. Budgets
**URL**: `/finance/budgets/`

| Feature | Description |
|---------|-------------|
| Annual Budgets | Create yearly budgets |
| Account-level | Budget per GL account |
| Monthly Breakdown | 12-month distribution |
| Variance Analysis | Compare budget vs actual |

---

### 8. VAT Returns (UAE)
**URL**: `/finance/vat-returns/`

| Feature | Description |
|---------|-------------|
| FTA Compliant | UAE Federal Tax Authority format |
| Auto-Calculation | Calculate from transactions |
| Box Mapping | Map accounts to VAT boxes |
| Submission Tracking | Track filing status |

**VAT Boxes (UAE):**
- Box 1: Standard rated supplies
- Box 2: Tax refunds
- Box 3: Zero-rated supplies
- Box 4: Exempt supplies
- Box 5: Total value of supplies
- Box 6: Standard rated expenses
- Box 7: Supplies subject to reverse charge
- Box 8: Total value of expenses
- Box 9: Total VAT due
- Box 10: Recoverable VAT
- Box 11: Net VAT payable/refundable

---

### 9. Tax Codes
**URL**: `/finance/tax-codes/`

| Feature | Description |
|---------|-------------|
| Multiple Codes | Define various VAT rates |
| Rate Management | 0%, 5%, Exempt, etc. |
| Default Code | Set default for transactions |

---

### 10. Opening Balances
**URL**: `/finance/opening-balances/`

| Feature | Description |
|---------|-------------|
| Migration Entry | Enter opening balances |
| Multi-account | All accounts in one entry |
| Balance Validation | Must balance to zero |
| Post & Lock | Lock after posting |

---

### 11. Write-Offs / Adjustments
**URL**: `/finance/write-offs/`

| Feature | Description |
|---------|-------------|
| Bad Debt Write-off | Write off uncollectible AR |
| Inventory Adjustment | Inventory write-offs |
| Approval Workflow | Create → Approve → Post |
| Reversal | Reverse if needed |

**Write-Off Types:**
- `bad_debt` - Bad debt write-off
- `inventory` - Inventory adjustment
- `asset` - Asset write-off
- `other` - Other adjustments

---

### 12. Exchange Rates
**URL**: `/finance/exchange-rates/`

| Feature | Description |
|---------|-------------|
| Multi-Currency | Support foreign currencies |
| Daily Rates | Rate per date |
| FX Revaluation | Period-end revaluation |

---

### 13. Account Mapping (SAP/Oracle Style)
**URL**: `/finance/account-mapping/`

| Feature | Description |
|---------|-------------|
| Account Determination | Map transaction types to accounts |
| One-Time Setup | Configure once, use everywhere |
| Module-wise | Sales, Purchase, Payroll, etc. |
| Auto-Posting | Transactions use mapped accounts |

**Mapped Transaction Types:**
- Sales: AR, Revenue, VAT Payable
- Purchase: AP, Expense, VAT Recoverable
- Expense Claims: Employee Payable
- Payroll: Salary Expense, Salary Payable
- Banking: Bank Charges, Interest
- General: FX Gain/Loss, Retained Earnings

---

### 14. Accounting Settings
**URL**: `/finance/settings/accounting/`

| Feature | Description |
|---------|-------------|
| Auto-Post Control | Enable/disable per module |
| VAT Settings | Default rate, TRN |
| Period Control | Approval requirements |
| Rounding | Fils rounding (2 decimals) |

---

## 📊 Reports

### Core Financial Statements

| Report | URL | Description |
|--------|-----|-------------|
| **Trial Balance** | `/finance/reports/trial-balance/` | All account balances with debit/credit totals |
| **Profit & Loss** | `/finance/reports/profit-loss/` | Income statement (Revenue - Expenses) |
| **Balance Sheet** | `/finance/reports/balance-sheet/` | Assets = Liabilities + Equity |
| **Cash Flow** | `/finance/reports/cash-flow/` | Cash movements (Operating, Investing, Financing) |

### Ledger Reports

| Report | URL | Description |
|--------|-----|-------------|
| **General Ledger** | `/finance/reports/general-ledger/` | All transactions by account |
| **Journal Register** | `/finance/reports/journal-register/` | All journal entries (audit report) |
| **Bank Ledger** | `/finance/reports/bank-ledger/` | Bank account transactions |

### AR/AP Reports

| Report | URL | Description |
|--------|-----|-------------|
| **AR Aging** | `/finance/reports/ar-aging/` | Customer receivables by age (30/60/90+ days) |
| **AP Aging** | `/finance/reports/ap-aging/` | Vendor payables by age |

### Budget Reports

| Report | URL | Description |
|--------|-----|-------------|
| **Budget vs Actual** | `/finance/reports/budget-vs-actual/` | Compare budgeted vs actual amounts |

### Statutory Reports (UAE)

| Report | URL | Description |
|--------|-----|-------------|
| **VAT Report** | `/finance/reports/vat/` | VAT summary for filing |
| **VAT Audit Report** | `/finance/reports/vat-audit/` | Detailed VAT transaction audit |
| **Corporate Tax** | `/finance/reports/corporate-tax/` | Corporate tax computation (9% UAE) |

### Reconciliation Reports

| Report | URL | Description |
|--------|-----|-------------|
| **Reconciliation Statement** | `/finance/reports/reconciliation-statement/` | Bank reconciliation summary |
| **Unreconciled Transactions** | `/finance/reports/unreconciled-transactions/` | Pending reconciliation items |
| **Reconciliation Adjustments** | `/finance/reports/reconciliation-adjustments/` | Adjustments made during reconciliation |
| **Cleared vs Uncleared** | `/finance/reports/cleared-vs-uncleared/` | Cleared transactions status |
| **Bank vs GL** | `/finance/reports/bank-vs-gl/` | Compare bank balance to GL |

---

## 🔄 Posting Flows (SAP/Oracle Standard)

### Sales Invoice Flow
```
Draft → Posted (Dr AR, Cr Revenue, Cr VAT) → Payment Received (Dr Bank, Cr AR)
```

### Vendor Bill Flow
```
Draft → Posted (Dr Expense, Dr VAT, Cr AP) → Payment Made (Dr AP, Cr Bank)
```

### Expense Claim Flow
```
Draft → Submitted → Approved (Dr Expense, Cr Employee Payable) → Paid (Dr Employee Payable, Cr Bank)
```

### Payroll Flow
```
Draft → Processed (Dr Salary Expense, Cr Salary Payable) → Paid (Dr Salary Payable, Cr Bank)
```

---

## 🔐 Security & Permissions

| Permission | Description |
|------------|-------------|
| `finance.view` | View all finance data |
| `finance.create` | Create new records |
| `finance.edit` | Edit existing records |
| `finance.delete` | Soft delete records |
| `finance.approve` | Approve transactions |
| `finance.post` | Post to ledger |

---

## 📝 Audit Trail

All finance transactions maintain:
- Created by / Created at
- Modified by / Modified at
- Posted by / Posted at
- Reversal tracking
- Soft delete (is_active flag)

---

## 🏷️ UAE Compliance

| Requirement | Implementation |
|-------------|----------------|
| VAT (5%) | Tax codes, VAT returns, FTA boxes |
| Corporate Tax (9%) | Tax computation report |
| TRN | Tax Registration Number tracking |
| Bilingual | English/Arabic invoice support |
| FTA Format | VAT return in FTA format |

---

## 📦 Database Models

| Model | Purpose |
|-------|---------|
| `Account` | Chart of Accounts |
| `FiscalYear` | Fiscal year management |
| `AccountingPeriod` | Monthly periods |
| `JournalEntry` | Journal header |
| `JournalEntryLine` | Journal lines (debit/credit) |
| `Payment` | Payment records |
| `BankAccount` | Bank account master |
| `BankTransfer` | Inter-bank transfers |
| `BankStatement` | Bank statement header |
| `BankStatementLine` | Statement transactions |
| `BankReconciliation` | Reconciliation record |
| `ReconciliationItem` | Reconciliation line items |
| `ExpenseClaim` | Expense claim header |
| `ExpenseItem` | Expense claim lines |
| `Budget` | Budget header |
| `BudgetLine` | Budget by account |
| `VATReturn` | VAT return filing |
| `CorporateTaxComputation` | Corporate tax calc |
| `TaxCode` | VAT rate codes |
| `OpeningBalanceEntry` | Opening balance header |
| `OpeningBalanceLine` | Opening balance lines |
| `WriteOff` | Write-off/adjustment |
| `ExchangeRate` | Currency rates |
| `AccountMapping` | Account determination |
| `AccountingSettings` | Global settings |

---

## 🚀 Quick Start

1. **Setup Chart of Accounts** → `/finance/accounts/`
2. **Configure Account Mapping** → `/finance/account-mapping/`
3. **Create Fiscal Year** → `/finance/fiscal-years/`
4. **Enter Opening Balances** → `/finance/opening-balances/`
5. **Start Transactions** → Invoices, Bills, Payments
6. **Run Reports** → Trial Balance, P&L, Balance Sheet

---

## 📞 Support

For issues or feature requests, contact the development team.

---

*Last Updated: January 2026*
*Version: 1.0*
*Compliance: UAE VAT Law, Corporate Tax Law, IFRS*




