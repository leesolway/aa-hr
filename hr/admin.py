from django.contrib import admin
from django.contrib.auth import get_user_model

from corptools.models import CharacterTitle

from .models import (
    AuditLog,
    DashboardSnooze,
    HrConfiguration,
    LabelCategory,
    MemberLabel,
    MemberLabelAssignment,
    Rank,
    RankAssignment,
    Role,
    RoleAssignment,
)
from .services import assign_label, assign_rank, remove_label

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

        home_corp_id = config.home_corp.corporation_id if config.home_corp_id else None

        users = (
            User.objects.filter(profile__state=config.aa_state)
            .prefetch_related(
                "character_ownerships__character__characteraudit__characterroles__titles",
                "hr_rank_assignments",
            )
        )
        if home_corp_id:
            users = users.filter(profile__main_character__corporation_id=home_corp_id)

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
                if home_corp_id and char.corporation_id != home_corp_id:
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


@admin.register(DashboardSnooze)
class DashboardSnoozeAdmin(admin.ModelAdmin):
    list_display = ["user", "snoozed_by", "snoozed_at", "expires_at", "note"]
    search_fields = ["user__profile__main_character__character_name", "note"]
    readonly_fields = ["snoozed_at"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "action", "user", "performed_by", "notes"]
    list_filter = ["action"]
    search_fields = ["user__profile__main_character__character_name"]
    readonly_fields = [
        "timestamp", "action", "user", "performed_by", "notes",
        "old_rank", "new_rank", "old_status", "new_status", "label",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False



@admin.register(LabelCategory)
class LabelCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "display_order", "description"]
    list_editable = ["display_order"]
    ordering = ["display_order", "name"]


@admin.register(MemberLabel)
class MemberLabelAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "auth_group", "is_active", "member_assignable", "description"]
    list_editable = ["is_active", "member_assignable"]
    list_filter = ["category", "is_active", "member_assignable"]
    search_fields = ["name", "description"]
    actions = ["sync_from_group"]

    @admin.action(description="Sync label assignments from AA group membership")
    def sync_from_group(self, request, queryset):
        User = get_user_model()
        total_added = 0
        total_removed = 0
        skipped = 0

        for label in queryset.select_related("auth_group").prefetch_related("assignments"):
            if not label.auth_group:
                skipped += 1
                continue

            group_user_ids = set(
                label.auth_group.user_set.values_list("pk", flat=True)
            )
            assigned_user_ids = set(
                label.assignments.values_list("user_id", flat=True)
            )

            # Add label for users in the group that lack an assignment
            for user in User.objects.filter(pk__in=group_user_ids - assigned_user_ids):
                assign_label(
                    user, label,
                    assigned_by=request.user,
                    notes="Retroactive sync from group membership",
                )
                total_added += 1

            # Remove label for users with an assignment no longer in the group
            orphaned = label.assignments.filter(
                user_id__in=assigned_user_ids - group_user_ids
            ).select_related("user")
            for assignment in orphaned:
                remove_label(
                    assignment.user, label,
                    performed_by=request.user,
                    notes="Sync cleanup: user not in group",
                )
                total_removed += 1

        parts = []
        if total_added:
            parts.append(f"{total_added} assignment(s) added")
        if total_removed:
            parts.append(f"{total_removed} orphaned assignment(s) removed")
        if skipped:
            parts.append(f"{skipped} label(s) skipped (no group linked)")

        self.message_user(
            request,
            "Sync complete: " + ", ".join(parts) + "." if parts else "Nothing to sync.",
        )


@admin.register(MemberLabelAssignment)
class MemberLabelAssignmentAdmin(admin.ModelAdmin):
    list_display = ["user", "label", "assigned_by", "assigned_at"]
    list_filter = ["label"]
    search_fields = ["user__profile__main_character__character_name"]
    readonly_fields = ["assigned_at"]


@admin.register(Rank)
class RankAdmin(admin.ModelAdmin):
    list_display = ["name", "priority", "auth_group", "corp_title", "is_active"]
    list_editable = ["priority", "is_active"]
    ordering = ["priority"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "corp_title":
            config = HrConfiguration.get_solo()
            if config.home_corp:
                kwargs["queryset"] = (
                    CharacterTitle.objects.filter(
                        corporation_id=config.home_corp.corporation_id
                    )
                    .order_by("title")
                )
            elif config.aa_state:
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


