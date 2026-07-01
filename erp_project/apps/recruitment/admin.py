from django.contrib import admin

from .models import Candidate, Position, RecruitmentRequest

admin.site.register(Position)
admin.site.register(RecruitmentRequest)
admin.site.register(Candidate)
