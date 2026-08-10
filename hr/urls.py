from django.urls import path

from . import views

app_name = "hr"

urlpatterns = [
    path("", views.dashboard, name="index"),
    path("me/", views.member_dashboard, name="me"),
    path("me/label/<int:label_id>/", views.self_assign_label, name="self_assign_label"),
    path("me/status/", views.self_set_status, name="self_set_status"),
    path("members/", views.member_list, name="member_list"),
    path("user/<int:user_id>/", views.member_detail, name="member_detail"),
    path("user/<int:user_id>/set-rank/", views.set_rank, name="set_rank"),
    path("user/<int:user_id>/set-status/", views.set_status, name="set_status"),
    path("user/<int:user_id>/set-label/", views.set_label, name="set_label"),
    path("user/<int:user_id>/set-role/", views.set_role, name="set_role"),
    path("unregistered/", views.unregistered, name="unregistered"),
    path("audit/", views.audit, name="audit"),
    path("user/<int:user_id>/fix/", views.fix_member, name="fix_member"),
    path("user/<int:user_id>/snooze/", views.snooze_warning, name="snooze_warning"),
    path("user/<int:user_id>/snooze/clear/", views.clear_snooze, name="clear_snooze"),
]
