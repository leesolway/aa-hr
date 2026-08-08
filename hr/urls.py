from django.urls import path

from . import views

app_name = "hr"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("members/", views.member_list, name="member_list"),
    path("user/<int:user_id>/", views.member_detail, name="member_detail"),
    path("user/<int:user_id>/set-rank/", views.set_rank, name="set_rank"),
    path("roles/", views.roles, name="roles"),
    path("unregistered/", views.unregistered, name="unregistered"),
    path("audit/", views.audit, name="audit"),
]
