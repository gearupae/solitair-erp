"""
Finance URL configuration - UAE VAT & Corporate Tax Compliant
Full enterprise-grade accounting module.
"""
from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    # ============ CHART OF ACCOUNTS ============
    path('accounts/', views.AccountListView.as_view(), name='account_list'),
    path('accounts/<int:pk>/edit/', views.AccountUpdateView.as_view(), name='account_edit'),
    path('accounts/<int:pk>/delete/', views.account_delete, name='account_delete'),
    
    # ============ FISCAL YEARS & PERIODS ============
    path('fiscal-years/', views.FiscalYearListView.as_view(), name='fiscalyear_list'),
    path('fiscal-years/<int:pk>/close/', views.fiscalyear_close, name='fiscalyear_close'),
    path('periods/', views.AccountingPeriodListView.as_view(), name='period_list'),
    path('periods/<int:pk>/lock/', views.period_lock, name='period_lock'),
    
    # ============ JOURNAL ENTRIES ============
    path('journal/', views.JournalEntryListView.as_view(), name='journal_list'),
    path('journal/create/', views.JournalEntryCreateView.as_view(), name='journal_create'),
    path('journal/<int:pk>/', views.JournalEntryDetailView.as_view(), name='journal_detail'),
    path('journal/<int:pk>/edit/', views.JournalEntryUpdateView.as_view(), name='journal_edit'),
    path('journal/<int:pk>/post/', views.journal_post, name='journal_post'),
    path('journal/<int:pk>/reverse/', views.journal_reverse, name='journal_reverse'),
    path('journal/<int:pk>/delete/', views.journal_delete, name='journal_delete'),
    
    # ============ PAYMENTS ============
    path('payments/', views.PaymentListView.as_view(), name='payment_list'),
    path('payments/create/', views.PaymentCreateView.as_view(), name='payment_create'),
    path('payments/<int:pk>/', views.PaymentDetailView.as_view(), name='payment_detail'),
    path('payments/<int:pk>/edit/', views.PaymentUpdateView.as_view(), name='payment_edit'),
    path('payments/<int:pk>/post/', views.payment_post, name='payment_post'),
    path('payments/<int:pk>/cancel/', views.payment_cancel, name='payment_cancel'),
    path('payments/<int:pk>/delete/', views.payment_delete, name='payment_delete'),
    
    # ============ BANKING ============
    path('bank-accounts/', views.BankAccountListView.as_view(), name='bankaccount_list'),
    path('bank-accounts/<int:pk>/edit/', views.BankAccountUpdateView.as_view(), name='bankaccount_edit'),
    path('bank-transfers/', views.BankTransferListView.as_view(), name='banktransfer_list'),
    path('bank-transfers/create/', views.BankTransferCreateView.as_view(), name='banktransfer_create'),
    path('bank-transfers/<int:pk>/confirm/', views.banktransfer_confirm, name='banktransfer_confirm'),
    
    # ============ BANK STATEMENTS (RECONCILIATION) ============
    path('bank-statements/', views.BankStatementListView.as_view(), name='bankstatement_list'),
    path('bank-statements/create/', views.BankStatementCreateView.as_view(), name='bankstatement_create'),
    path('bank-statements/template/', views.bankstatement_template_download, name='bankstatement_template'),
    path('bank-statements/<int:pk>/', views.BankStatementDetailView.as_view(), name='bankstatement_detail'),
    path('bank-statements/<int:pk>/import/', views.bankstatement_import, name='bankstatement_import'),
    path('bank-statements/<int:pk>/add-line/', views.bankstatement_add_line, name='bankstatement_add_line'),
    path('bank-statements/<int:pk>/auto-match/', views.bankstatement_auto_match, name='bankstatement_auto_match'),
    path('bank-statements/<int:pk>/line/<int:line_id>/match/', views.bankstatement_manual_match, name='bankstatement_manual_match'),
    path('bank-statements/<int:pk>/line/<int:line_id>/unmatch/', views.bankstatement_unmatch, name='bankstatement_unmatch'),
    path('bank-statements/<int:pk>/line/<int:line_id>/adjustment/', views.bankstatement_adjustment, name='bankstatement_adjustment'),
    path('bank-statements/<int:pk>/finalize/', views.bankstatement_finalize, name='bankstatement_finalize'),
    path('bank-statements/<int:pk>/lock/', views.bankstatement_lock, name='bankstatement_lock'),
    
    # ============ BANK RECONCILIATION ============
    path('reconciliations/', views.BankReconciliationListView.as_view(), name='bankreconciliation_list'),
    path('reconciliations/create/', views.BankReconciliationCreateView.as_view(), name='bankreconciliation_create'),
    path('reconciliations/<int:pk>/', views.BankReconciliationDetailView.as_view(), name='bankreconciliation_detail'),
    path('reconciliations/<int:pk>/complete/', views.bankreconciliation_complete, name='bankreconciliation_complete'),
    path('reconciliations/<int:pk>/approve/', views.bankreconciliation_approve, name='bankreconciliation_approve'),
    
    # ============ EXPENSE CLAIMS ============
    path('expense-claims/', views.ExpenseClaimListView.as_view(), name='expenseclaim_list'),
    path('expense-claims/create/', views.ExpenseClaimCreateView.as_view(), name='expenseclaim_create'),
    path('expense-claims/<int:pk>/', views.ExpenseClaimDetailView.as_view(), name='expenseclaim_detail'),
    path('expense-claims/<int:pk>/submit/', views.expenseclaim_submit, name='expenseclaim_submit'),
    path('expense-claims/<int:pk>/approve/', views.expenseclaim_approve, name='expenseclaim_approve'),
    
    # ============ BUDGETS ============
    path('budgets/', views.BudgetListView.as_view(), name='budget_list'),
    path('budgets/create/', views.BudgetCreateView.as_view(), name='budget_create'),
    path('budgets/<int:pk>/', views.BudgetDetailView.as_view(), name='budget_detail'),
    
    # ============ VAT RETURNS (UAE) ============
    path('vat-returns/', views.VATReturnListView.as_view(), name='vatreturn_list'),
    path('vat-returns/create/', views.VATReturnCreateView.as_view(), name='vatreturn_create'),
    path('vat-returns/<int:pk>/', views.VATReturnDetailView.as_view(), name='vatreturn_detail'),
    path('vat-returns/<int:pk>/edit/', views.VATReturnUpdateView.as_view(), name='vatreturn_edit'),
    path('vat-returns/<int:pk>/post/', views.vatreturn_post, name='vatreturn_post'),
    path('vat-returns/<int:pk>/reverse/', views.vatreturn_reverse, name='vatreturn_reverse'),
    path('vat-returns/<int:pk>/submit/', views.vatreturn_submit_to_fta, name='vatreturn_submit'),
    
    # ============ TAX CODES ============
    path('tax-codes/', views.TaxCodeListView.as_view(), name='taxcode_list'),
    
    # ============ FINANCIAL REPORTS (UAE Compliant) ============
    
    # Core Financial Statements
    path('reports/trial-balance/', views.trial_balance, name='trial_balance'),
    path('reports/trial-balance-movements/', views.trial_balance_with_movements, name='trial_balance_with_movements'),
    path('reports/profit-loss/', views.profit_loss, name='profit_loss'),
    path('reports/balance-sheet/', views.balance_sheet, name='balance_sheet'),
    path('reports/cash-flow/', views.cash_flow, name='cash_flow'),
    
    # Ledger Reports
    path('reports/general-ledger/', views.general_ledger, name='general_ledger'),
    path('reports/journal-register/', views.journal_register, name='journal_register'),
    path('reports/journal-register/<int:pk>/', views.journal_register_detail, name='journal_register_detail'),
    path('reports/bank-ledger/', views.bank_ledger, name='bank_ledger'),
    
    # AR/AP Reports
    path('reports/ar-aging/', views.ar_aging, name='ar_aging'),
    path('reports/ap-aging/', views.ap_aging, name='ap_aging'),
    
    # Budget Reports
    path('reports/budget-vs-actual/', views.budget_vs_actual, name='budget_vs_actual'),
    
    # Statutory Reports (UAE)
    path('reports/vat/', views.vat_report, name='vat_report'),
    path('reports/corporate-tax/', views.corporate_tax_report, name='corporate_tax_report'),
    path('reports/corporate-tax/create/', views.corporate_tax_create, name='corporate_tax_create'),
    path('reports/corporate-tax/<int:pk>/recalculate/', views.corporate_tax_recalculate, name='corporate_tax_recalculate'),
    path('reports/corporate-tax/<int:pk>/post-provision/', views.corporate_tax_post_provision, name='corporate_tax_post_provision'),
    path('reports/corporate-tax/<int:pk>/pay/', views.corporate_tax_pay, name='corporate_tax_pay'),
    
    # ============ RECONCILIATION REPORTS ============
    path('reports/reconciliation-statement/', views.reconciliation_statement_report, name='reconciliation_statement_report'),
    path('reports/unreconciled-transactions/', views.unreconciled_transactions_report, name='unreconciled_transactions_report'),
    path('reports/reconciliation-adjustments/', views.reconciliation_adjustments_report, name='reconciliation_adjustments_report'),
    path('reports/cleared-vs-uncleared/', views.cleared_vs_uncleared_report, name='cleared_vs_uncleared_report'),
    path('reports/bank-vs-gl/', views.bank_vs_gl_report, name='bank_vs_gl_report'),
    
    # ============ OPENING BALANCES ============
    path('opening-balances/', views.OpeningBalanceListView.as_view(), name='openingbalance_list'),
    path('opening-balances/create/', views.OpeningBalanceCreateView.as_view(), name='openingbalance_create'),
    path('opening-balances/<int:pk>/', views.OpeningBalanceDetailView.as_view(), name='openingbalance_detail'),
    path('opening-balances/<int:pk>/edit/', views.OpeningBalanceUpdateView.as_view(), name='openingbalance_edit'),
    path('opening-balances/<int:pk>/post/', views.openingbalance_post, name='openingbalance_post'),
    path('opening-balances/<int:pk>/reverse/', views.openingbalance_reverse, name='openingbalance_reverse'),
    
    # System Opening Balance Edit (editable before fiscal year lock)
    path('opening-balances/system/edit/', views.system_opening_balance_edit, name='system_opening_balance_edit'),
    path('opening-balances/system/add-line/', views.system_opening_balance_add_line, name='system_opening_balance_add_line'),
    path('opening-balances/system/delete-line/<int:line_id>/', views.system_opening_balance_delete_line, name='system_opening_balance_delete_line'),
    
    # Seed FY 2025 Opening Balance (web trigger)
    path('opening-balances/seed-fy2025/', views.seed_fy2025_opening_balance, name='seed_fy2025_opening_balance'),
    
    # ============ WRITE-OFFS / ADJUSTMENTS ============
    path('write-offs/', views.WriteOffListView.as_view(), name='writeoff_list'),
    path('write-offs/create/', views.WriteOffCreateView.as_view(), name='writeoff_create'),
    path('write-offs/<int:pk>/', views.WriteOffDetailView.as_view(), name='writeoff_detail'),
    path('write-offs/<int:pk>/edit/', views.WriteOffUpdateView.as_view(), name='writeoff_edit'),
    path('write-offs/<int:pk>/approve/', views.writeoff_approve, name='writeoff_approve'),
    path('write-offs/<int:pk>/post/', views.writeoff_post, name='writeoff_post'),
    path('write-offs/<int:pk>/reverse/', views.writeoff_reverse, name='writeoff_reverse'),
    
    # ============ EXCHANGE RATES ============
    path('exchange-rates/', views.ExchangeRateListView.as_view(), name='exchangerate_list'),
    path('exchange-rates/create/', views.ExchangeRateCreateView.as_view(), name='exchangerate_create'),
    path('exchange-rates/<int:pk>/edit/', views.ExchangeRateUpdateView.as_view(), name='exchangerate_edit'),
    
    # ============ VAT AUDIT REPORT ============
    path('reports/vat-audit/', views.vat_audit_report, name='vat_audit_report'),
    
    # ============ ACCOUNT MAPPING / ACCOUNT DETERMINATION ============
    path('account-mapping/', views.account_mapping_list, name='account_mapping_list'),
    path('account-mapping/save/', views.account_mapping_save, name='account_mapping_save'),
    path('settings/accounting/', views.accounting_settings, name='accounting_settings'),
]
