"""
Purchase URL configuration - Including Expense Claims and Recurring Expenses
"""
from django.urls import path
from . import views
from . import views_procurement
from . import views_expense_public

app_name = 'purchase'

urlpatterns = [
    # Dashboard
    path('dashboard/', views.PurchaseDashboardView.as_view(), name='dashboard'),

    # Vendors
    path('vendors/', views.VendorListView.as_view(), name='vendor_list'),
    path('vendors/<int:pk>/edit/', views.VendorUpdateView.as_view(), name='vendor_edit'),
    path('vendors/<int:pk>/delete/', views.vendor_delete, name='vendor_delete'),
    
    # Purchase Requests
    path('requests/', views.PurchaseRequestListView.as_view(), name='pr_list'),
    path('requests/create/', views.PurchaseRequestCreateView.as_view(), name='pr_create'),
    path('requests/<int:pk>/', views.PurchaseRequestDetailView.as_view(), name='pr_detail'),
    path('requests/<int:pk>/pdf/', views.pr_pdf, name='pr_pdf'),
    path('requests/<int:pk>/edit/', views.PurchaseRequestUpdateView.as_view(), name='pr_edit'),
    path('requests/<int:pk>/submit/', views.pr_submit, name='pr_submit'),
    path('requests/<int:pk>/return/', views.pr_return, name='pr_return'),
    path('requests/<int:pk>/delete/', views.pr_delete, name='pr_delete'),
    path('requests/<int:pk>/approve/', views.pr_approve, name='pr_approve'),
    path('requests/<int:pk>/reject/', views.pr_reject, name='pr_reject'),
    path('requests/<int:pk>/convert/', views.pr_convert, name='pr_convert'),
    path('requests/<int:pk>/items/', views.pr_items_json, name='pr_items_json'),
    path(
        'requests/<int:pk>/vendor-attachments/upload/',
        views.pr_vendor_attachment_upload,
        name='pr_vendor_attachment_upload',
    ),
    path(
        'requests/<int:pk>/vendor-attachments/<int:attachment_id>/',
        views.pr_vendor_attachment_update,
        name='pr_vendor_attachment_update',
    ),
    path(
        'requests/<int:pk>/vendor-quotes/analyze/',
        views.pr_vendor_quote_analyze,
        name='pr_vendor_quote_analyze',
    ),
    path(
        'requests/<int:pk>/vendor-quotes/analyze/status/',
        views.pr_vendor_quote_analyze_status,
        name='pr_vendor_quote_analyze_status',
    ),
    
    # Purchase Orders
    path('orders/', views.PurchaseOrderListView.as_view(), name='po_list'),
    path('orders/create/', views.PurchaseOrderCreateView.as_view(), name='po_create'),
    path('orders/<int:pk>/', views.PurchaseOrderDetailView.as_view(), name='po_detail'),
    path('orders/<int:pk>/receive/', views.po_receive, name='po_receive'),
    path('orders/<int:pk>/confirm/', views.po_confirm, name='po_confirm'),
    path('orders/<int:pk>/pdf/', views.po_pdf, name='po_pdf'),
    path('orders/<int:pk>/ai-evaluate/', views.po_ai_evaluate, name='po_ai_evaluate'),
    path('orders/<int:pk>/send-email/', views.po_send_email, name='po_send_email'),
    path('orders/<int:pk>/edit/', views.PurchaseOrderUpdateView.as_view(), name='po_edit'),
    path('orders/<int:pk>/delete/', views.po_delete, name='po_delete'),
    path('orders/<int:pk>/items/', views.po_items_json, name='po_items_json'),
    path('orders/<int:pk>/retention/', views.po_save_retention, name='po_save_retention'),
    path('orders/<int:pk>/convert-bill/', views.po_convert_to_bill, name='po_convert_bill'),
    path('api/po/<int:pk>/retention/', views.po_retention_json, name='po_retention_json'),
    path('api/project/<int:pk>/purchase-retention/', views.project_purchase_retention_json, name='project_purchase_retention_json'),
    
    # Vendor Bills
    path('bills/', views.VendorBillListView.as_view(), name='bill_list'),
    path('bills/create/', views.VendorBillCreateView.as_view(), name='bill_create'),
    path('bills/<int:pk>/', views.VendorBillDetailView.as_view(), name='bill_detail'),
    path('bills/<int:pk>/edit/', views.VendorBillUpdateView.as_view(), name='bill_edit'),
    path('bills/<int:pk>/delete/', views.bill_delete, name='bill_delete'),
    path('bills/<int:pk>/submit/', views.bill_submit, name='bill_submit'),
    path('bills/<int:pk>/approve/', views.bill_approve, name='bill_approve'),
    path('bills/<int:pk>/reject/', views.bill_reject, name='bill_reject'),
    path('bills/<int:pk>/return/', views.bill_return, name='bill_return'),
    path('bills/<int:pk>/post/', views.bill_post, name='bill_post'),
    path('bills/<int:pk>/pay/', views.bill_make_payment, name='bill_pay'),
    
    # Expense Claims (moved from Finance)
    path('expense-claims/', views.ExpenseClaimListView.as_view(), name='expenseclaim_list'),
    path('expense-claims/create/', views.ExpenseClaimCreateView.as_view(), name='expenseclaim_create'),
    path('expense-claims/public/submit/', views_expense_public.PublicExpenseClaimView.as_view(), name='public_expense_claim'),
    path('expense-claims/public/done/', views_expense_public.PublicExpenseClaimDoneView.as_view(), name='public_expense_claim_done'),
    path('expense-claims/public/lookup/', views_expense_public.public_expense_claim_lookup, name='public_expense_claim_lookup'),
    path('expense-claims/<int:pk>/', views.ExpenseClaimDetailView.as_view(), name='expenseclaim_detail'),
    path('expense-claims/<int:pk>/edit/', views.ExpenseClaimUpdateView.as_view(), name='expenseclaim_edit'),
    path('expense-claims/<int:pk>/submit/', views.expenseclaim_submit, name='expenseclaim_submit'),
    path('expense-claims/<int:pk>/approve/', views.expenseclaim_approve, name='expenseclaim_approve'),
    path('expense-claims/<int:pk>/reject/', views.expenseclaim_reject, name='expenseclaim_reject'),
    path('expense-claims/<int:pk>/pay/', views.expenseclaim_pay, name='expenseclaim_pay'),
    
    # Recurring Expenses (NEW)
    path('recurring-expenses/', views.RecurringExpenseListView.as_view(), name='recurringexpense_list'),
    path('recurring-expenses/create/', views.RecurringExpenseCreateView.as_view(), name='recurringexpense_create'),
    path('recurring-expenses/<int:pk>/', views.RecurringExpenseDetailView.as_view(), name='recurringexpense_detail'),
    path('recurring-expenses/<int:pk>/edit/', views.RecurringExpenseUpdateView.as_view(), name='recurringexpense_edit'),
    path('recurring-expenses/<int:pk>/delete/', views.recurringexpense_delete, name='recurringexpense_delete'),
    path('recurring-expenses/<int:pk>/execute/', views.recurringexpense_execute, name='recurringexpense_execute'),
    path('recurring-expenses/<int:pk>/pause/', views.recurringexpense_pause, name='recurringexpense_pause'),
    path('recurring-expenses/<int:pk>/resume/', views.recurringexpense_resume, name='recurringexpense_resume'),

    # Goods Receipt Notes (formal GRN)
    path('grn/', views_procurement.GRNListView.as_view(), name='grn_list'),
    path('grn/<int:pk>/', views_procurement.GRNDetailView.as_view(), name='grn_detail'),
    path('grn/<int:pk>/cancel/', views_procurement.grn_cancel, name='grn_cancel'),

    # RFQ / Competitive Purchase Analysis
    path('rfq/', views_procurement.RFQListView.as_view(), name='rfq_list'),
    path('rfq/<int:pk>/', views_procurement.RFQDetailView.as_view(), name='rfq_detail'),
    path('rfq/<int:pk>/award/', views_procurement.rfq_award, name='rfq_award'),
    path('rfq/<int:pk>/convert-po/', views_procurement.rfq_convert_po, name='rfq_convert_po'),
    path('rfq/<int:pk>/pull-mr/', views_procurement.rfq_pull_mr, name='rfq_pull_mr'),
]

