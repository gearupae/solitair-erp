"""
Purchase URL configuration - Including Expense Claims and Recurring Expenses
"""
from django.urls import path
from . import views

app_name = 'purchase'

urlpatterns = [
    # Vendors
    path('vendors/', views.VendorListView.as_view(), name='vendor_list'),
    path('vendors/<int:pk>/edit/', views.VendorUpdateView.as_view(), name='vendor_edit'),
    path('vendors/<int:pk>/delete/', views.vendor_delete, name='vendor_delete'),
    
    # Purchase Requests
    path('requests/', views.PurchaseRequestListView.as_view(), name='pr_list'),
    path('requests/create/', views.PurchaseRequestCreateView.as_view(), name='pr_create'),
    path('requests/<int:pk>/', views.PurchaseRequestDetailView.as_view(), name='pr_detail'),
    path('requests/<int:pk>/edit/', views.PurchaseRequestUpdateView.as_view(), name='pr_edit'),
    path('requests/<int:pk>/submit/', views.pr_submit, name='pr_submit'),
    path('requests/<int:pk>/return/', views.pr_return, name='pr_return'),
    path('requests/<int:pk>/delete/', views.pr_delete, name='pr_delete'),
    path('requests/<int:pk>/approve/', views.pr_approve, name='pr_approve'),
    path('requests/<int:pk>/reject/', views.pr_reject, name='pr_reject'),
    path('requests/<int:pk>/convert/', views.pr_convert, name='pr_convert'),
    path('requests/<int:pk>/items/', views.pr_items_json, name='pr_items_json'),
    
    # Purchase Orders
    path('orders/', views.PurchaseOrderListView.as_view(), name='po_list'),
    path('orders/create/', views.PurchaseOrderCreateView.as_view(), name='po_create'),
    path('orders/<int:pk>/', views.PurchaseOrderDetailView.as_view(), name='po_detail'),
    path('orders/<int:pk>/edit/', views.PurchaseOrderUpdateView.as_view(), name='po_edit'),
    path('orders/<int:pk>/delete/', views.po_delete, name='po_delete'),
    path('orders/<int:pk>/items/', views.po_items_json, name='po_items_json'),
    
    # Vendor Bills
    path('bills/', views.VendorBillListView.as_view(), name='bill_list'),
    path('bills/create/', views.VendorBillCreateView.as_view(), name='bill_create'),
    path('bills/<int:pk>/', views.VendorBillDetailView.as_view(), name='bill_detail'),
    path('bills/<int:pk>/edit/', views.VendorBillUpdateView.as_view(), name='bill_edit'),
    path('bills/<int:pk>/delete/', views.bill_delete, name='bill_delete'),
    path('bills/<int:pk>/post/', views.bill_post, name='bill_post'),
    path('bills/<int:pk>/pay/', views.bill_make_payment, name='bill_pay'),
    
    # Expense Claims (moved from Finance)
    path('expense-claims/', views.ExpenseClaimListView.as_view(), name='expenseclaim_list'),
    path('expense-claims/create/', views.ExpenseClaimCreateView.as_view(), name='expenseclaim_create'),
    path('expense-claims/<int:pk>/', views.ExpenseClaimDetailView.as_view(), name='expenseclaim_detail'),
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
]

