"""Recruitment URL configuration."""
from django.urls import path

from . import views

app_name = 'recruitment'

urlpatterns = [
    path('requests/', views.RecruitmentRequestListView.as_view(), name='request_list'),
    path('requests/create/', views.RecruitmentRequestCreateView.as_view(), name='request_create'),
    path('requests/<int:pk>/', views.RecruitmentRequestDetailView.as_view(), name='request_detail'),
    path('requests/<int:pk>/edit/', views.RecruitmentRequestUpdateView.as_view(), name='request_edit'),
    path('requests/<int:pk>/approve/', views.recruitment_request_approve, name='request_approve'),
    path('requests/<int:pk>/reject/', views.recruitment_request_reject, name='request_reject'),
    path('candidates/', views.CandidateListView.as_view(), name='candidate_list'),
    path('candidates/create/', views.CandidateCreateView.as_view(), name='candidate_create'),
    path('candidates/<int:pk>/', views.CandidateDetailView.as_view(), name='candidate_detail'),
    path('candidates/<int:pk>/edit/', views.CandidateUpdateView.as_view(), name='candidate_edit'),
    path(
        'candidates/<int:candidate_pk>/convert/',
        views.CandidateConvertEmployeeView.as_view(),
        name='candidate_convert',
    ),
    path('candidates/kanban/move/', views.candidate_kanban_move, name='candidate_kanban_move'),
    path('settings/', views.recruitment_settings, name='settings'),
]
