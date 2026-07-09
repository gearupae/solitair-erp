from django.urls import path

from . import views

app_name = 'operations'

urlpatterns = [
    path('', views.StaffDutyScheduleListView.as_view(), name='schedule_list'),
    path('dashboard/', views.StaffDutyDashboardView.as_view(), name='schedule_dashboard'),
    path('create/', views.StaffDutyScheduleCreateView.as_view(), name='schedule_create'),
    path('calendar/', views.StaffDutyCalendarView.as_view(), name='schedule_calendar'),
    path('availability/', views.staff_availability_check, name='availability_check'),
    path('public/<uuid:token>/', views.public_staff_schedule, name='public_schedule'),
    path('<int:pk>/edit/', views.StaffDutyScheduleUpdateView.as_view(), name='schedule_edit'),
    path('<int:pk>/pause/', views.staff_duty_pause, name='schedule_pause'),
    path('<int:pk>/resume/', views.staff_duty_resume, name='schedule_resume'),
    path('<int:pk>/delete/', views.staff_duty_delete, name='schedule_delete'),
]
