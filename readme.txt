Django ERP System - Development Guide
Project Overview
Build a minimal, modular ERP system using Django, Bootstrap, PostgreSQL. Keep it simple and expandable for client customization.
Tech Stack
* Backend: Django 5.x
* Frontend: Bootstrap 5, jQuery
* Database: PostgreSQL
* Authentication: Django built-in
________________


Project Structure
erp_project/
├── apps/
│   ├── core/
│   ├── crm/
│   ├── sales/
│   ├── purchase/
│   ├── inventory/
│   ├── finance/
│   ├── projects/
│   ├── hr/
│   ├── documents/
      |—-  Doc expiry
│   └── settings/
├── static/
├── media/
└── templates/


________________


Common Fields for All Models
Every model should have:
* created_at
* updated_at
* created_by (link to User)
* updated_by (link to User)
* is_active
________________


MODULE 1: CRM
* name
* email
* phone
* company
* address
* Status
* Type = lead/customer/
Pages Needed:
* Add button to add customer with above field- form will be inline and not popup, and all added details should be listed in table, in table there should be action button with view, edit, delete - make sure permission is set for all buttons based on roles allocated 
________________


MODULE 2: SALES
Quotation
* quotation_number (auto)
* customer (link)
* date
* Status = draft/send/approved/rejected
* notes
* Item selection from inventory
* Terms and condition
Page overview
* A create button for quotation as inline form and not popup with above details, and all added details should be listed in table, in table there should be action button with view, edit, delete - make sure permission is set for all buttons based on roles allocated 


Invoice
* invoice_number (auto)
* quotation (link)
* customer (link)
* invoice_date
* due_date
* status
* total_amount
* paid_amount
* Balance
* items
Page overview
* A create button for invoice as inline form and not popup with above details, and all added details should be listed in table, in table there should be action button with view, edit, delete - make sure permission is set for all buttons based on roles allocated 


________________


MODULE 3: PURCHASE
Vendor
* Vendor name
* name
* email
* phone
* address
* status
PurchaseRequest
* pr_number (auto)
* date
* requested_by
* required_by_date
* status
* Total_amount 
* Items from inventory


PurchaseOrder
* po_number (auto)
* vendor (link)
* order_date
* expected_delivery_date
* status
* Total_amount
* Item from inventory
VendorBill
* bill_number (auto)
* purchase_order (link)
* vendor (link)
* bill_date
* due_date
* status
* total_amount
* paid_amount
* Balance


Pages required
* A create button for vendor,purchase request ,purchase order , vendor bill - separate buttons as inline form and not popup with above details, and all added details should be listed in separate table,[vendor table, purchase request table, purchase order table] in table there should be action button with view, edit, delete - make sure permission is set for all buttons based on roles allocated 


________________


MODULE 4: INVENTORY
Category
* name
* parent_category (link to self)
* description
Warehouse
* name
* location
* is_active
Item
* item_code (auto)
* name
* image
* category (link)
* unit_of_measure
* sale_price
* current_stock
Pages Needed:
* Item list, create, edit with image upload
* Stock levels with low stock alerts
* Stock movement history
* Inventory reports
________________


MODULE 5: FINANCE / ACCOUNTS
UAE VAT & Corporate Tax Compliant – FINAL SPECIFICATION
________________


1. LEGAL & ACCOUNTING FRAMEWORK (MANDATORY)
This module must comply with:
* UAE VAT Law – Federal Decree-Law No. 8 of 2017

* UAE Corporate Tax Law – Federal Decree-Law No. 47 of 2022

* IFRS-based financial reporting (mandatory in UAE)

* Accrual accounting (default method)

Core principles:
   * Double-entry accounting (Debit = Credit)

   * Period-based reporting

   * Audit trail mandatory

   * No hard deletion of financial records

________________


2. DATA MODEL (UNCHANGED – CONFIRMED)
Account
      * account_code (auto)

      * account_name

      * account_type (Asset / Liability / Equity / Income / Expense)

      * parent_account (self-link)

      * opening_balance

      * current_balance

JournalEntry
         * entry_number (auto)

         * date

         * reference

         * description

         * status (Draft / Posted / Locked / Reversed)

JournalLine
            * journal_entry (link)

            * account (link)

            * debit

            * credit

            * description

Payment
               * payment_number (auto)

               * payment_date

               * payment_type (Received / Made)

               * party_type (Customer / Vendor)

               * party_id

               * amount

               * payment_method

               * reference_number

               * status

BankAccount
                  * account_name

                  * account_number

                  * bank_name

                  * current_balance

                  * currency

ExpenseClaim
                     * claim_number (auto)

                     * employee (link)

                     * claim_date

                     * total_amount

                     * status

ExpenseItem
                        * expense_claim (link)

                        * date

                        * category

                        * description

                        * amount

                        * receipt (file)

________________


3. CHART OF ACCOUNTS (UAE STANDARD)
Assets
                           * Cash

                           * Bank Accounts

                           * Accounts Receivable

                           * VAT Recoverable (Input VAT)

                           * Prepaid Expenses

                           * Fixed Assets

                           * Accumulated Depreciation

Liabilities
                              * Accounts Payable

                              * VAT Payable (Output VAT)

                              * Corporate Tax Payable

                              * Accrued Expenses

Equity
                                 * Owner’s Capital

                                 * Retained Earnings

                                 * Current Year Profit/Loss

Income
                                    * Sales – Taxable (5%)

                                    * Sales – Zero Rated

                                    * Sales – Exempt

                                    * Other Income

Expenses
                                       * Cost of Goods Sold

                                       * Operating Expenses

                                       * Salaries

                                       * Rent

                                       * Utilities

                                       * Depreciation

                                       * Non-Deductible Expenses (Corporate Tax)

Rules:
                                          * Posting allowed only to leaf accounts

                                          * Parent accounts are reporting-only

                                          * Abnormal balances must be flagged

________________


4. JOURNAL ENTRY (CORE LEDGER ENGINE)
Usage
                                             * Manual entries

                                             * Opening balances

                                             * Accruals

                                             * Depreciation

                                             * VAT adjustments

                                             * Corporate tax provisions

                                             * Year-end closing

Mandatory Validations
                                                * Total Debit = Total Credit

                                                * Minimum 2 JournalLines

                                                * Date must be within open period

                                                * Posted entries cannot be edited or deleted

Controls
                                                   * Back-dated entries require permission + reason

                                                   * All deletions replaced by reversal entries

                                                   * Attachments mandatory for tax-related journals

________________


5. PAYMENTS
Accounting Impact
Payment Type
	Debit
	Credit
	Received
	Bank / Cash
	Accounts Receivable
	Made
	Accounts Payable
	Bank / Cash
	Rules:
                                                      * Payments do not create VAT

                                                      * Partial payments allowed

                                                      * Overpayments tracked as advances

                                                      * Cancellation creates auto-reversal journal

________________


6. BANK ACCOUNT & RECONCILIATION
Rules:
                                                         * BankAccount must map to a GL Account

                                                         * current_balance is system-calculated only

                                                         * GL balance and bank balance may differ until reconciled

                                                         * Unreconciled transactions must be reportable

________________


7. EXPENSE CLAIMS (VAT INPUT COMPLIANCE)
Rules:
                                                            * VAT claimable only with valid receipt

                                                            * VAT posted to VAT Recoverable

                                                            * Non-deductible expenses flagged for Corporate Tax

                                                            * Employee advances adjusted automatically

Accounting Entry (on approval):
Debit
	Credit
	Expense Account
	Employee Payable / Cash
	VAT Recoverable
	

	________________


8. VAT MANAGEMENT (UAE – 5%)
VAT Types
                                                               * Standard Rated (5%)

                                                               * Zero Rated

                                                               * Exempt

                                                               * Out of Scope

VAT Accounts
                                                                  * VAT Payable (Liability)

                                                                  * VAT Recoverable (Asset)

Rules:
                                                                     * VAT never mixed with income/expense

                                                                     * VAT rounded to 2 decimals

                                                                     * VAT adjustments require reason & reference

                                                                     * VAT periods: Monthly or Quarterly

                                                                     * Period locked after filing (FTA requirement)

VAT Reports (FTA-ready)
                                                                        * Taxable supplies

                                                                        * Zero-rated supplies

                                                                        * Exempt supplies

                                                                        * Output VAT

                                                                        * Input VAT

                                                                        * Net VAT payable / refundable

________________


9. CORPORATE TAX (UAE – 9%)
Rules:
                                                                           * Tax applies only if profit > AED 375,000

                                                                           * Based on accounting profit

                                                                           * Adjusted for:

                                                                              * Non-deductible expenses

                                                                              * Exempt income

Corporate Tax Entry:
Debit
	Credit
	Corporate Tax Expense
	Corporate Tax Payable
	Reports:
                                                                                 * Accounting Profit

                                                                                 * Adjustments

                                                                                 * Taxable Income

                                                                                 * Tax Payable

________________


10. FINANCIAL REPORTS (MANDATORY)
Core Reports
                                                                                    1. Trial Balance

                                                                                    2. Profit & Loss (Before & After Tax)

                                                                                    3. Balance Sheet

                                                                                    4. Cash Flow Statement

                                                                                    5. General Ledger

                                                                                    6. Journal Register

Statutory Reports
                                                                                       * VAT Return (FTA format)

                                                                                       * VAT Audit Report

                                                                                       * Corporate Tax Computation

                                                                                       * Retained Earnings Statement

________________


11. PERIOD CLOSING & CONTROLS
Month-End
                                                                                          * Lock journals

                                                                                          * VAT review

                                                                                          * Trial balance freeze

Year-End
                                                                                             * Transfer profit to retained earnings

                                                                                             * Lock fiscal year

                                                                                             * Auto-create next year opening balances

________________


12. AUDIT & SECURITY
                                                                                                * Sequential numbering mandatory

                                                                                                * Full audit trail (user, date, IP)

                                                                                                * No hard delete

                                                                                                * Read-only auditor access

                                                                                                * Reversals only

________________


13. COMPLETE TEST CASES (FOR DEVELOPERS)
Core Accounting
                                                                                                   * Unbalanced journal → Block

                                                                                                   * Posting to parent account → Block

                                                                                                   * Locked period entry → Block

Payments
                                                                                                      * Partial payment → Balance remains

                                                                                                      * Overpayment → Advance created

                                                                                                      * Cancel payment → Reversal journal

VAT
                                                                                                         * VAT expense with receipt → VAT Recoverable

                                                                                                         * Zero-rated sale → Reported separately

                                                                                                         * VAT period locked → No posting

Corporate Tax
                                                                                                            * Profit < 375,000 → No tax

                                                                                                            * Profit > 375,000 → Correct 9% tax

                                                                                                            * Non-deductible expense → Excluded

Reporting
                                                                                                               * Trial Balance → Must balance

                                                                                                               * Balance Sheet → Assets = Liabilities + Equity

                                                                                                               * Retained earnings → Prior profit carried forward

Audit
                                                                                                                  * Delete journal → Not allowed

                                                                                                                  * Reverse journal → Auto-entry

                                                                                                                  * Audit log → Mandatory


Test case for accounting module
Below is the FINAL, DETAILED & COMPLETE TEST CASE DOCUMENT
This is developer-ready, QA-ready, and audit-ready for UAE-compliant ERP Accounting.
You can share this directly with PM, developers, and testers.
________________


MODULE 5 – FINANCE / ACCOUNTS
✅ COMPLETE TEST CASES (UAE VAT & CORPORATE TAX COMPLIANT)
________________


A. CHART OF ACCOUNTS (ACCOUNT)
TC-A01: Create Leaf Account
Input: Create account under Expenses
Expected: Account saved successfully
TC-A02: Duplicate Account Code
Input: Manually duplicate account_code
Expected: System blocks save
TC-A03: Parent Account Posting
Input: Post journal to parent account
Expected: Error – posting allowed only to leaf accounts
TC-A04: Abnormal Balance Detection
Input: Credit balance in Expense account
Expected: System flags abnormal balance
TC-A05: Opening Balance Lock
Input: Edit opening balance after posting
Expected: Edit blocked
________________


B. JOURNAL ENTRY
TC-J01: Balanced Journal
Input: Debit = Credit
Expected: Journal saved and posted
TC-J02: Unbalanced Journal
Input: Debit ≠ Credit
Expected: Save blocked
TC-J03: Single Line Journal
Input: Only one journal line
Expected: Error – minimum 2 lines required
TC-J04: Backdated Journal (Permission)
Input: Date before current period
Expected: Permission + reason required
TC-J05: Edit Posted Journal
Input: Edit after status = Posted
Expected: Edit blocked
TC-J06: Delete Journal
Input: Delete journal entry
Expected: Delete blocked
TC-J07: Reverse Journal
Input: Reverse posted journal
Expected: New reversal entry auto-created
________________


C. PAYMENTS
TC-P01: Customer Payment (Full)
Input: Invoice 10,000 → Payment 10,000
Expected: AR cleared, Bank increased
TC-P02: Partial Payment
Input: Invoice 10,000 → Payment 4,000
Expected: Balance due = 6,000
TC-P03: Overpayment
Input: Invoice 10,000 → Payment 12,000
Expected: 2,000 posted as Customer Advance
TC-P04: Vendor Payment
Input: Payment to vendor
Expected: AP reduced, Bank reduced
TC-P05: Cancel Payment
Input: Cancel posted payment
Expected: Auto reversal journal created
TC-P06: Payment Status Flow
Expected Flow: Draft → Posted → Reconciled
________________


D. BANK ACCOUNT & RECONCILIATION
TC-B01: Bank Balance Auto Update
Input: Payment posted
Expected: BankAccount current_balance updated
TC-B02: Manual Bank Balance Edit
Input: Edit bank balance manually
Expected: Edit blocked
TC-B03: Unreconciled Transaction
Input: Payment not matched to bank
Expected: Appears in unreconciled list
TC-B04: Bank Reconciliation
Input: Match statement entry
Expected: Status = Reconciled
________________


E. EXPENSE CLAIMS
TC-E01: Expense Claim Submission
Input: Employee submits claim
Expected: Status = Submitted
TC-E02: Expense Approval
Input: Manager approves
Expected: Journal entry auto-created
TC-E03: Expense With VAT & Receipt
Input: 1,000 + VAT 50
Expected:
                                                                                                                     * Expense = 1,000
                                                                                                                     * VAT Recoverable = 50
TC-E04: Expense Without Receipt
Input: VAT expense without receipt
Expected: VAT not recoverable
TC-E05: Non-Deductible Expense
Input: Mark as non-deductible
Expected: Excluded from Corporate Tax calc
________________


F. VAT (UAE – 5%)
TC-V01: Standard Rated Sale
Input: Sale 10,000
Expected:
                                                                                                                     * Output VAT = 500
                                                                                                                     * VAT Payable updated
TC-V02: Zero Rated Sale
Input: Zero-rated supply
Expected: VAT = 0, reported separately
TC-V03: Exempt Sale
Expected: No VAT, excluded from VAT calc
TC-V04: VAT Rounding
Input: VAT with decimals
Expected: Rounded to 2 decimals
TC-V05: VAT Adjustment Entry
Input: Adjustment journal
Expected: Reason mandatory
TC-V06: VAT Period Lock
Input: Post entry after VAT filed
Expected: Entry blocked
TC-V07: Negative VAT
Input: Input VAT > Output VAT
Expected: VAT Refund shown
________________


G. CORPORATE TAX (UAE – 9%)
TC-C01: Profit Below Threshold
Input: Profit = 300,000
Expected: Tax = 0
TC-C02: Profit Above Threshold
Input: Profit = 500,000
Expected:
(500,000 − 375,000) × 9%
TC-C03: Non-Deductible Expense
Input: Entertainment expense
Expected: Excluded from tax base
TC-C04: Corporate Tax Provision
Input: Year-end provision
Expected:
Debit Tax Expense
Credit Tax Payable
TC-C05: Edit Tax Entry
Input: Edit posted tax entry
Expected: Edit blocked, reversal only
________________


H. REPORTING
TC-R01: Trial Balance
Expected: Total Debit = Total Credit
TC-R02: Profit & Loss
Expected:
Net Profit = Income − Expenses − Tax
TC-R03: Balance Sheet
Expected: Assets = Liabilities + Equity
TC-R04: Cash Flow
Expected: Matches bank movements
TC-R05: VAT Report
Expected: Matches ledger totals
TC-R06: Corporate Tax Report
Expected: Matches accounting profit & adjustments
________________


I. PERIOD CLOSING
TC-CL01: Month Lock
Input: Lock month
Expected: No posting allowed
TC-CL02: Year-End Closing
Input: Close financial year
Expected:
                                                                                                                     * Profit transferred to retained earnings
                                                                                                                     * Next year opening balances created
________________


J. AUDIT & SECURITY
TC-AU01: Audit Log
Expected: User, timestamp, action logged
TC-AU02: Sequential Numbering
Expected: No gaps in journal numbers
TC-AU03: Read-Only Auditor Role
Expected: No edit/delete access
________________




________________


MODULE 6: PROJECTS
Project
                                                                                                                     * Project name
                                                                                                                     * customer (link)
                                                                                                                     * start_date
                                                                                                                     * end_date
                                                                                                                     * budget
                                                                                                                     * status
                                                                                                                     * project_manager
Task
                                                                                                                     * project (link)
                                                                                                                     * title
                                                                                                                     * assigned_to
                                                                                                                     * priority
                                                                                                                     * start_date
                                                                                                                     * due_date
                                                                                                                     * status
Pages Needed:
                                                                                                                     * Project list and detail with task board
                                                                                                                     * Task create, edit with drag-drop
                                                                                                                     * Timesheet entry
                                                                                                                     * Project dashboard
________________


MODULE 7: HR
Department
                                                                                                                     * name
                                                                                                                     * head (link to Employee)
Designation
                                                                                                                     * title
                                                                                                                     * department (link)
Employee
                                                                                                                     * employee_id (auto)
                                                                                                                     * user (link)
                                                                                                                     * first_name
                                                                                                                     * last_name
                                                                                                                     * email
                                                                                                                     * phone
                                                                                                                     * department (link)
                                                                                                                     * designation (link)
                                                                                                                     * join_date
                                                                                                                     * status
                                                                                                                     * salary
LeaveType
                                                                                                                     * name
                                                                                                                     * days_allowed
LeaveApplication
                                                                                                                     * employee (link)
                                                                                                                     * leave_type (link)
                                                                                                                     * from_date
                                                                                                                     * to_date
                                                                                                                     * days
                                                                                                                     * reason
                                                                                                                     * status
Payroll
                                                                                                                     * employee (link)
                                                                                                                     * month
                                                                                                                     * year
                                                                                                                     * basic_salary
                                                                                                                     * allowances
                                                                                                                     * deductions
                                                                                                                     * net_salary
                                                                                                                     * status
Pages Needed:
                                                                                                                     * Employee directory
                                                                                                                     * Attendance calendar view
                                                                                                                     * Leave application and approval
                                                                                                                     * Payroll processing
                                                                                                                     * HR dashboard
________________


MODULE 8:
Doc Expiry 
                                                                                                                     1. Name field, date field, reminder field  so user can add any name and expiry date and say number of days and add button so these data will show in table and it will be notified before the number of days provided 


MODULE 9: SETTINGS
User Management
Role
                                                                                                                     * name
                                                                                                                     * code
                                                                                                                     * description
                                                                                                                     * is_system_role
Permission
                                                                                                                     * module (CRM/Sales/Purchase/etc)
                                                                                                                     * name
                                                                                                                     * code
                                                                                                                     * permission_type (view/create/edit/delete/approve)
RolePermission
                                                                                                                     * role (link)
                                                                                                                     * permission (link)
                                                                                                                     * can_create
                                                                                                                     * can_read
                                                                                                                     * can_update
                                                                                                                     * can_delete
                                                                                                                     * can_approve
UserRole
                                                                                                                     * user (link)
                                                                                                                     * role (link)
                                                                                                                     * assigned_date
UserProfile
                                                                                                                     * user (link)
                                                                                                                     * employee (link)
                                                                                                                     * phone
                                                                                                                     * profile_picture
                                                                                                                     * timezone
                                                                                                                     * preferred_language
________________


Approval  automtically 
User will select module and the person to be approved then it will be approved or else it will be auto approved 


Module include purchase request only no other module need approval 
________________


Email & Notifications
EmailAccount
                                                                                                                     * account_name
                                                                                                                     * email_address
                                                                                                                     * smtp_host
                                                                                                                     * smtp_port
                                                                                                                     * username
                                                                                                                     * password (encrypted)
                                                                                                                     * use_tls
                                                                                                                     * is_default
EmailTemplate
                                                                                                                     * name
                                                                                                                     * code
                                                                                                                     * subject
                                                                                                                     * body_html
                                                                                                                     * variables
                                                                                                                     * module
Notification
                                                                                                                     * recipient (link to User)
                                                                                                                     * title
                                                                                                                     * message
                                                                                                                     * notification_type
                                                                                                                     * is_read
                                                                                                                     * created_at
                                                                                                                     * action_url
________________


System Configuration
CompanySettings
                                                                                                                     * company_name
                                                                                                                     * logo
                                                                                                                     * address
                                                                                                                     * phone
                                                                                                                     * email
                                                                                                                     * tax_id
                                                                                                                     * fiscal_year_start
                                                                                                                     * currency
                                                                                                                     * date_format
                                                                                                                     * timezone
NumberSeries
                                                                                                                     * document_type
                                                                                                                     * prefix
                                                                                                                     * next_number
                                                                                                                     * padding
AuditLog
                                                                                                                     * user (link)
                                                                                                                     * action
                                                                                                                     * model
                                                                                                                     * record_id
                                                                                                                     * changes
                                                                                                                     * timestamp
                                                                                                                     * ip_address
________________


Settings Pages Needed:
                                                                                                                     1. User Management:

                                                                                                                        * User list with role assignment
                                                                                                                        * Role management with permission checkboxes
                                                                                                                        * Permission matrix by role
                                                                                                                        2. Approval Workflows:

                                                                                                                           * Workflow configuration
                                                                                                                           * Pending approvals dashboard
                                                                                                                           * Approval history
                                                                                                                           3. Email Settings:

                                                                                                                              * SMTP configuration with test button
                                                                                                                              4. System Settings:

                                                                                                                                 * Company profile form
                                                                                                                                 * Number series setup
                                                                                                                                 * Audit log viewer with filters
                                                                                                                                 * System preferences
                                                                                                                                 5. Authentication:

                                                                                                                                    * Login/Logout
________________


Navigation Menu Structure
Dashboard
├── CRM (Customers, Leads)
├── Sales (Quotations, Orders, Invoices)
├── Purchase (Vendors, Requests, Orders, Bills)
├── Inventory (Items, Categories, Stock)
├── Finance (Accounts, Journal, Payments, Expenses, Reports)
├── Projects (Projects, Tasks)
├── HR (Employees, Attendance, Leaves, Payroll)
├── Documents (All Documents, Categories)
└── Settings (Users, Roles, Approvals, Email, Company, Logs)


________________


Key Features to Implement
1. Permission System
                                                                                                                                    * Check permissions on every view
                                                                                                                                    * Show/hide menu items based on permissions
                                                                                                                                    * Users see only their own records
                                                                                                                                    * Managers see department records
                                                                                                                                    * Admins see everything
2. Approval Workflow
                                                                                                                                    * When document created → create approval request
                                                                                                                                    * Notify approvers
                                                                                                                                    * Lock document from editing
                                                                                                                                    * On approval → move to next level
                                                                                                                                    * On rejection → notify creator, allow editing
3. Number Series Generator
                                                                                                                                    * Auto-generate document numbers
                                                                                                                                    * Format: PREFIX-YEAR-NUMBER
                                                                                                                                    * Example: INV-2025-0001
4. Audit Logging
                                                                                                                                    * Track all changes
                                                                                                                                    * Store old and new values
                                                                                                                                    * Log user and timestamp
                                                                                                                                    * Display in audit viewer
5. Email Integration
                                                                                                                                    * Use templates with variables
                                                                                                                                    * Send invoices, quotations via email
                                                                                                                                    * Approval notifications
                                                                                                                                    * Password reset emails
________________


Frontend Requirements
Base Template Features:
                                                                                                                                    * Bootstrap 5
                                                                                                                                    * jQuery
                                                                                                                                    * Font Awesome icons
                                                                                                                                    * DataTables for lists
                                                                                                                                    * Select2 for dropdowns
                                                                                                                                    * DatePicker for dates
                                                                                                                                    * Toastr for notifications
                                                                                                                                    * Responsive sidebar
                                                                                                                                    * Top navbar with user menu
Common UI Components:
                                                                                                                                    * List view with search, filter, export
                                                                                                                                    * Form with validation
                                                                                                                                    * Dashboard cards with counts
                                                                                                                                    * Modal for quick actions
                                                                                                                                    * Confirmation dialogs
                                                                                                                                    * Loading spinners
________________


Development Phases
Phase 1: Core Setup
                                                                                                                                    * Project structure
                                                                                                                                    * Authentication
                                                                                                                                    * Base templates
                                                                                                                                    * Settings module
Phase 2: Basic Modules
                                                                                                                                    * CRM
                                                                                                                                    * Inventory
                                                                                                                                    * Basic Sales
Phase 3: Advanced Modules
                                                                                                                                    * Purchase
                                                                                                                                    * Finance
                                                                                                                                    * Projects
                                                                                                                                    * HR
Phase 4: System Features
                                                                                                                                    * Email
                                                                                                                                    * Documents
                                                                                                                                    * Notifications
Phase 5: Polish
                                                                                                                                    * UI refinement
                                                                                                                                    * Testing
                                                                                                                                    * Bug fixes
________________


Initial Setup Data Needed
Default Roles:
                                                                                                                                    * Super Admin (all permissions)
                                                                                                                                    * Admin (most permissions)
                                                                                                                                    * Manager (department permissions)
                                                                                                                                    * Employee (limited permissions)
                                                                                                                                    * Accountant (finance permissions)
                                                                                                                                    * Sales (sales permissions)
                                                                                                                                    * Purchase (purchase permissions)
Default Chart of Accounts:
                                                                                                                                    * Assets (Bank, Cash, Inventory)
                                                                                                                                    * Liabilities (Accounts Payable)
                                                                                                                                    * Equity (Capital)
                                                                                                                                    * Income (Sales)
                                                                                                                                    * Expenses (Cost of Goods, Operating)
Default Email Templates:
                                                                                                                                    * Invoice sent
                                                                                                                                    * Quotation sent
                                                                                                                                    * Password reset
Default Number Series:
                                                                                                                                    * Customers: CUST-
                                                                                                                                    * Vendors: VEND-
                                                                                                                                    * Quotations: QUO-
                                                                                                                                    * Invoices: INV-
                                                                                                                                    * Purchase Requests: PR-
                                                                                                                                    * Purchase Orders: PO-
                                                                                                                                    * Bills: BILL-
                                                                                                                                    * Employees: EMP-
                                                                                                                                    * Projects: PROJ-
________________


Security Checklist
                                                                                                                                    * CSRF protection
                                                                                                                                    * Password hashing
                                                                                                                                    * SQL injection prevention (use ORM)
                                                                                                                                    * XSS protection (template escaping)
                                                                                                                                    * Permission checks on all views
                                                                                                                                    * Secure password reset
                                                                                                                                    * Session timeout
                                                                                                                                    * Audit logging
                                                                                                                                    * File upload validation
                                                                                                                                    * Rate limiting on login
________________


Performance Tips
                                                                                                                                    * Add database indexes on foreign keys
                                                                                                                                    * Use select_related for queries
                                                                                                                                    * Pagination on all lists
                                                                                                                                    * Cache dashboard counts
                                                                                                                                    * Lazy load images
                                                                                                                                    * Minify CSS/JS in production
________________


Expected Deliverables
                                                                                                                                    1. Working Django ERP application
                                                                                                                                    2. PostgreSQL database setup
                                                                                                                                    3. Responsive web interface
                                                                                                                                    4. Admin panel access
                                                                                                                                    5. Sample data loaded
                                                                                                                                    6. Setup instructions in README
________________


Important Notes
                                                                                                                                    * Keep EVERYTHING minimal and simple
                                                                                                                                    * Focus on functionality over fancy UI
                                                                                                                                    * Make number series flexible
                                                                                                                                    * Document complex logic
                                                                                                                                    * Clean, readable code for easy customization
Complete each module fully before moving to next. Prioritize working features over perfect design.