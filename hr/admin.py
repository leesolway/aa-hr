from django.contrib import admin
from django.contrib.auth import get_user_model

from corptools.models import CharacterTitle

from .models import (
    HrConfiguration,
    Rank,
    RankAssignment,
    RankAuditLog,
    Role,
    RoleAssignment,
)
from .services import assign_rank

User = get_user_model()


@admin.register(HrConfiguration)
class HrConfigurationAdmin(admin.ModelAdmin):
    actions = ["backfill_ranks_from_titles"]

    @admin.action(description="Backfill ranks from in-game titles (skips users already ranked)")
    def backfill_ranks_from_titles(self, request, queryset):
        config = HrConfiguration.get_solo()
        if not config.aa_state:
            self.message_user(request, "No state configured in HR Configuration.", level="error")
            return

        users = (
            User.objects.filter(profile__state=config.aa_state)
            .prefetch_related(
                "character_ownerships__character__characteraudit__characterroles__titles",
                "hr_rank_assignments",
            )
        )

        assigned = 0
        skipped = 0
        no_match = 0

        for user in users:
            if any(a.is_current for a in user.hr_rank_assignments.all()):
                skipped += 1
                continue

            title_pks = set()
            for ownership in user.character_ownerships.all():
                char = ownership.character
                if not char:
                    continue
                try:
                    for t in char.characteraudit.characterroles.titles.all():
                        title_pks.add(t.pk)
                except AttributeError:
                    pass

            if not title_pks:
                no_match += 1
                continue

            rank = (
                Rank.objects.filter(corp_title__in=title_pks, is_active=True)
                .order_by("-priority")
                .first()
            )
            if not rank:
                no_match += 1
                continue

            assign_rank(user, rank, assigned_by=request.user, notes="Backfilled from in-game titles")
            assigned += 1

        self.message_user(
            request,
            f"Backfill complete: {assigned} assigned, {skipped} skipped (already ranked), {no_match} no matching rank found.",
        )


@admin.register(Rank)
class RankAdmin(admin.ModelAdmin):
    list_display = ["name", "priority", "auth_group", "corp_title", "is_active"]
    list_editable = ["priority", "is_active"]
    ordering = ["priority"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "corp_title":
            config = HrConfiguration.get_solo()
            if config.aa_state:
                kwargs["queryset"] = (
                    CharacterTitle.objects.filter(
                        characterroles__character__character__character_ownership__user__profile__state=config.aa_state
                    )
                    .distinct()
                    .order_by("corporation_name", "title")
                )
            else:
                kwargs["queryset"] = CharacterTitle.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(RankAssignment)
class RankAssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "rank", "is_current", "assigned_by", "assigned_at"]
    list_filter = ["rank", "is_current"]
    search_fields = ["user__profile__main_character__character_name"]
    readonly_fields = ["assigned_at"]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["name"]
    filter_horizontal = ["can_assign", "can_remove"]


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "assigned_by", "assigned_at"]
    list_filter = ["role"]
    readonly_fields = ["assigned_at"]


@admin.register(RankAuditLog)
class RankAuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "action", "user", "old_rank", "new_rank", "performed_by"]
    list_filter = ["action", "new_rank"]
    search_fields = ["user__profile__main_character__character_name"]
    readonly_fields = ["timestamp"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
