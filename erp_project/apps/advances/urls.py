from django.urls import path
from . import views

app_name = 'advances'

urlpatterns = [
    # -----------------------------------------------------------------------
    # Customer Advance
    # -----------------------------------------------------------------------
    # Advance tab data for a customer — POST creates, GET used by detail template
    path(
        'customer-advances/for/<int:customer_pk>/',
        views.customer_advance_tab,
        name='customer_advance_tab',
    ),
    path(
        'customer-advances/<int:pk>/',
        views.customer_advance_detail,
        name='customer_advance_detail',
    ),
    path(
        'customer-advances/<int:pk>/post/',
        views.customer_advance_post,
        name='customer_advance_post',
    ),
    path(
        'customer-advances/<int:pk>/apply/',
        views.customer_advance_apply,
        name='customer_advance_apply',
    ),
    path(
        'customer-advances/<int:pk>/receipt/',
        views.customer_advance_receipt_pdf,
        name='customer_advance_receipt_pdf',
    ),

    # -----------------------------------------------------------------------
    # Vendor Detail + Vendor Advance
    # -----------------------------------------------------------------------
    path(
        'vendors/<int:pk>/',
        views.vendor_detail,
        name='vendor_detail',
    ),
    path(
        'vendor-advances/<int:pk>/',
        views.vendor_advance_detail,
        name='vendor_advance_detail',
    ),
    path(
        'vendor-advances/<int:pk>/post/',
        views.vendor_advance_post,
        name='vendor_advance_post',
    ),
    path(
        'vendor-advances/<int:pk>/apply/',
        views.vendor_advance_apply,
        name='vendor_advance_apply',
    ),

    # -----------------------------------------------------------------------
    # Security Cheques Outward
    # -----------------------------------------------------------------------
    path(
        'security-cheques/',
        views.SecurityChequeListView.as_view(),
        name='security_cheque_list',
    ),
    path(
        'security-cheques/create/',
        views.security_cheque_create,
        name='security_cheque_create',
    ),
    path(
        'security-cheques/<int:pk>/',
        views.security_cheque_detail,
        name='security_cheque_detail',
    ),
    path(
        'security-cheques/<int:pk>/encash/',
        views.security_cheque_encash,
        name='security_cheque_encash',
    ),
    path(
        'security-cheques/<int:pk>/return/',
        views.security_cheque_return,
        name='security_cheque_return',
    ),

    # -----------------------------------------------------------------------
    # API helpers
    # -----------------------------------------------------------------------
    path('api/vat-calc/', views.customer_advance_vat_api, name='vat_calc'),
]
