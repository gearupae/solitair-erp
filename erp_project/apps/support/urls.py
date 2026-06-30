from django.urls import path

from . import views

app_name = 'support'

urlpatterns = [
    path('', views.SupportTicketListView.as_view(), name='ticket_list'),
    path('create/', views.SupportTicketCreateView.as_view(), name='ticket_create'),
    path('public/', views.public_support_ticket_create, name='public_create'),
    path('public/search/', views.public_support_link_search, name='public_link_search'),
    path('kanban/move/', views.support_kanban_move, name='kanban_move'),
    path('<int:pk>/', views.SupportTicketDetailView.as_view(), name='ticket_detail'),
    path('<int:pk>/edit/', views.SupportTicketUpdateView.as_view(), name='ticket_edit'),
    path('<int:pk>/delete/', views.support_ticket_delete, name='ticket_delete'),
]
