from datetime import datetime, time as dt_time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from allianceauth.eveonline.models import EveCharacter

from .models import AuditLog, DashboardSnooze, HrConfiguration, LabelCategory, MemberLabel, MemberStatusAssignment, Role, RoleAssignment, Rank
from .services import (
    _build_alts,
    _current_assignment_from_prefetch,
    _get_member_status,
    assign_label,
    assign_rank,
    assign_role,
    clear_member_status,
    compute_member_alerts,
    get_current_rank,
    get_effective_assignable_ranks,
    get_effective_removable_rank_ids,
    prepare_members,
    remove_label,
    remove_rank,
    remove_role,
    set_member_status,
)

User = get_user_model()


def _label_category_qs(member_assignable_only=False):
    """Return (label_categories qs, uncategorised_labels qs) for use in views."""
    label_filters = {"labels__is_active": True}
    uncategorised_filters = {"is_active": True, "category__isnull": True}
    if member_assignable_only:
        label_filters["labels__member_assignable"] = True
        uncategorised_filters["member_assignable"] = True
    label_categories = (
        LabelCategory.objects.prefetch_related("labels")
        .filter(**label_filters)
        .distinct()
        .order_by("display_order", "name")
    )
    uncategorised_labels = MemberLabel.objects.filter(**uncategorised_filters)
    return label_categories, uncategorised_labels


def _has_any_role(user):
    return user.role_assignments.exists()


def _unregistered_chars_qs(state):
    """Queryset of EveCharacters in the given state that have no registered owner."""
    corp_ids = list(state.member_corporations.values_list("corporation_id", flat=True))
    alliance_ids = list(state.member_alliances.values_list("alliance_id", flat=True))
    return EveCharacter.objects.filter(
        Q(corporation_id__in=corp_ids) | Q(alliance_id__in=alliance_ids)
    ).filter(character_ownership__isnull=True)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
def dashboard(request):
    config = HrConfiguration.get_solo()

    if not config.aa_state:
        return render(request, "hr/dashboard.html", {"state": None})

    members = prepare_members(config)
    show_snoozed = request.GET.get("show_snoozed") == "1"

    total = len(members)

    now = timezone.now()
    active_snoozes = DashboardSnooze.objects.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).select_related("snoozed_by")
    snooze_map = {s.user_id: s for s in active_snoozes}
    snoozed_ids = set(snooze_map)

    def _is_issue(m):
        return (
            m["title_mismatch"]
            or m["stale_title_chars"]
            or (not m["rank"] and not m["rank_removed_by_status"])
            or m["has_audit_issue"]
            or m["has_role_title_mismatch"]
            or m["has_stale_role_title"]
        )

    def _not_snoozed(m):
        return show_snoozed or m["user"].pk not in snoozed_ids

    no_rank      = sum(1 for m in members if not m["rank"] and not m["rank_removed_by_status"] and _not_snoozed(m))
    mismatches   = sum(1 for m in members if m["title_mismatch"] and _not_snoozed(m))
    audit_issues = sum(1 for m in members if m["has_audit_issue"] and _not_snoozed(m))

    all_issue_members = [m for m in members if _is_issue(m)]
    for m in all_issue_members:
        if m["user"].pk in snoozed_ids:
            m["snooze"] = snooze_map[m["user"].pk]

    if show_snoozed:
        issue_members = all_issue_members
    else:
        issue_members = [m for m in all_issue_members if m["user"].pk not in snoozed_ids]

    has_snoozed = bool(snoozed_ids & {m["user"].pk for m in all_issue_members})
    unregistered_count = _unregistered_chars_qs(config.aa_state).count()

    return render(request, "hr/dashboard.html", {
        "state": config.aa_state,
        "total_members": total,
        "no_rank": no_rank,
        "title_mismatches": mismatches,
        "audit_issues": audit_issues,
        "issue_members": issue_members,
        "show_snoozed": show_snoozed,
        "has_snoozed": has_snoozed,
        "unregistered_count": unregistered_count,
    })


# ---------------------------------------------------------------------------
# Member list
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
def member_list(request):
    config = HrConfiguration.get_solo()

    if not config.aa_state:
        return render(request, "hr/members.html", {"members": [], "state": None})

    members = prepare_members(config)
    all_ranks = Rank.objects.filter(is_active=True)

    rank_filter = request.GET.get("rank", "")
    mismatch_filter = request.GET.get("mismatch", "")
    search = request.GET.get("search", "").strip().lower()

    if rank_filter == "none":
        members = [m for m in members if not m["rank"]]
    elif rank_filter.isdigit():
        members = [m for m in members if m["rank"] and m["rank"].pk == int(rank_filter)]

    if mismatch_filter == "1":
        members = [m for m in members if m["title_mismatch"]]

    audit_filter = request.GET.get("audit_issue", "")
    if audit_filter == "1":
        members = [m for m in members if m["has_audit_issue"]]

    if search:
        members = [
            m for m in members
            if search in m["main"].character_name.lower()
            or any(search in (a.character_name or "").lower() for a in m["alts"])
        ]

    paginator = Paginator(members, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "hr/members.html", {
        "state": config.aa_state,
        "page_obj": page_obj,
        "member_count": len(members),
        "all_ranks": all_ranks,
        "rank_filter": rank_filter,
        "mismatch_filter": mismatch_filter,
        "audit_filter": audit_filter,
        "search": request.GET.get("search", ""),
    })


# ---------------------------------------------------------------------------
# Member detail + rank assignment
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
def member_detail(request, user_id):
    config = HrConfiguration.get_solo()

    member_user = get_object_or_404(
        User.objects.select_related(
            "profile__main_character",
            "hr_member_status",
        ).prefetch_related(
            "character_ownerships__character__characteraudit__characterroles__titles",
            "hr_rank_assignments__rank__auth_group",
            "hr_rank_assignments__rank__corp_title",
            "hr_rank_assignments__assigned_by__profile__main_character",
            "role_assignments__role__corp_title",
            "hr_label_assignments__label__category",
        ),
        pk=user_id,
    )

    current_assignment = _current_assignment_from_prefetch(member_user.hr_rank_assignments.all())
    current_rank = current_assignment.rank if current_assignment else None

    assignable_ranks = get_effective_assignable_ranks(request.user)
    removable_rank_ids = get_effective_removable_rank_ids(request.user)

    can_assign = assignable_ranks.exists() or request.user.is_superuser
    can_remove = (
        current_rank and (
            current_rank.pk in removable_rank_ids or request.user.is_superuser
        )
    )

    if request.user.is_superuser:
        assignable_ranks = Rank.objects.filter(is_active=True)

    alerts = compute_member_alerts(member_user, config)

    audit_entries = AuditLog.objects.filter(user=member_user).select_related(
        "performed_by__profile__main_character",
        "old_rank", "new_rank", "label", "role",
    )
    audit_page = Paginator(audit_entries, 25).get_page(request.GET.get("audit_page"))

    main = getattr(member_user.profile, "main_character", None)
    alts = _build_alts(member_user, main) if main else []

    current_label_ids = {a.label_id for a in member_user.hr_label_assignments.all()}
    label_categories, uncategorised_labels = _label_category_qs()

    try:
        teamspeak3_user = member_user.teamspeak3
    except Exception:
        teamspeak3_user = None

    member_role_assignments = None
    all_roles = None
    if request.user.has_perm("hr.manage_roles"):
        member_role_assignments = (
            RoleAssignment.objects.filter(user=member_user)
            .select_related("role", "assigned_by__profile__main_character")
        )
        all_roles = Role.objects.all()

    return render(request, "hr/member_detail.html", {
        "member_user": member_user,
        "main": main,
        "alts": alts,
        "current_rank": current_rank,
        "current_assignment": current_assignment,
        "missing_title_chars": alerts["missing_title_chars"],
        "stale_title_chars": alerts["stale_title_chars"],
        "audit_issue_chars": alerts["audit_issue_chars"],
        "role_title_mismatches": alerts["role_title_mismatches"],
        "stale_role_title_chars": alerts["stale_role_title_chars"],
        "current_status_assignment": alerts["member_status"],
        "assignable_ranks": assignable_ranks,
        "can_assign": can_assign,
        "can_remove": can_remove,
        "audit_page": audit_page,
        "current_label_ids": current_label_ids,
        "label_categories": label_categories,
        "uncategorised_labels": uncategorised_labels,
        "teamspeak3_user": teamspeak3_user,
        "member_role_assignments": member_role_assignments,
        "all_roles": all_roles,
    })


@login_required
@permission_required("hr.access_hr")
@require_POST
def set_rank(request, user_id):
    member_user = get_object_or_404(User, pk=user_id)
    rank_id = request.POST.get("rank_id", "").strip()
    notes = request.POST.get("notes", "").strip()

    assignable_ranks = get_effective_assignable_ranks(request.user)
    removable_rank_ids = get_effective_removable_rank_ids(request.user)

    if rank_id == "0":
        current = get_current_rank(member_user)
        if current and (
            current.rank.pk in removable_rank_ids or request.user.is_superuser
        ):
            remove_rank(member_user, performed_by=request.user, notes=notes)
            messages.success(request, f"Rank removed from {member_user}.")
        else:
            return HttpResponseForbidden("You cannot remove this rank.")
    elif rank_id.isdigit():
        rank = get_object_or_404(Rank, pk=int(rank_id), is_active=True)
        assignable_ids = set(assignable_ranks.values_list("pk", flat=True))
        if rank.pk not in assignable_ids and not request.user.is_superuser:
            return HttpResponseForbidden("You cannot assign this rank.")
        assign_rank(member_user, rank, assigned_by=request.user, notes=notes)
        messages.success(request, f"{member_user} assigned rank {rank.name}.")
    else:
        messages.error(request, "Invalid rank selection.")

    return redirect("hr:member_detail", user_id=user_id)


# ---------------------------------------------------------------------------
# Member status
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
@require_POST
def set_status(request, user_id):
    if not (_has_any_role(request.user) or request.user.is_superuser):
        return HttpResponseForbidden("You do not have an HR role.")

    member_user = get_object_or_404(User, pk=user_id)
    notes = request.POST.get("notes", "").strip()

    status = request.POST.get("status", "").strip()
    valid = {v for v, _ in MemberStatusAssignment.STATUS_CHOICES}
    if status not in valid:
        messages.error(request, "Invalid status.")
        return redirect("hr:member_detail", user_id=user_id)

    if status == MemberStatusAssignment.ACTIVE:
        cleared = clear_member_status(member_user, set_by=request.user, notes=notes)
        if cleared:
            messages.success(request, f"Status cleared for {member_user}.")
        else:
            messages.info(request, f"{member_user} had no active status.")
    else:
        set_member_status(member_user, status=status, set_by=request.user, notes=notes)
        messages.success(request, f"{member_user} status set to '{dict(MemberStatusAssignment.STATUS_CHOICES)[status]}'.")

    return redirect("hr:member_detail", user_id=user_id)


# ---------------------------------------------------------------------------
# Member self-service dashboard
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.member_access")
def member_dashboard(request):
    """Self-service dashboard: members view their own rank/status and toggle their own labels."""
    user = request.user

    current_assignment = (
        user.hr_rank_assignments.filter(is_current=True)
        .select_related("rank")
        .first()
    )
    current_rank = current_assignment.rank if current_assignment else None

    current_status_assignment = _get_member_status(user)

    current_label_ids = set(
        user.hr_label_assignments.values_list("label_id", flat=True)
    )

    label_categories, uncategorised_labels = _label_category_qs(member_assignable_only=True)

    try:
        main = user.profile.main_character
    except AttributeError:
        main = None

    # Build character list with audit status
    characters = []
    for ownership in (
        user.character_ownerships
        .select_related("character__characteraudit")
        .all()
    ):
        char = ownership.character
        if not char:
            continue
        try:
            audit_active = char.characteraudit.active
            audit_status = "ok" if audit_active else "stale"
        except AttributeError:
            audit_status = "missing"
        is_main = main and char.character_id == main.character_id
        characters.append({
            "char": char,
            "is_main": is_main,
            "audit_status": audit_status,
        })
    characters.sort(key=lambda c: (not c["is_main"], c["char"].character_name))
    has_audit_issue = any(c["audit_status"] != "ok" for c in characters)

    role_assignments = (
        RoleAssignment.objects.filter(user=user)
        .select_related("role")
        .prefetch_related("role__can_assign", "role__can_remove")
    )

    audit_page = Paginator(
        AuditLog.objects.filter(user=user)
        .select_related("old_rank", "new_rank", "label", "performed_by__profile__main_character"),
        10,
    ).page(1)

    try:
        teamspeak3_user = user.teamspeak3
    except Exception:
        teamspeak3_user = None

    return render(request, "hr/member_dashboard.html", {
        "main": main,
        "current_rank": current_rank,
        "current_status_assignment": current_status_assignment,
        "current_label_ids": current_label_ids,
        "label_categories": label_categories,
        "uncategorised_labels": uncategorised_labels,
        "characters": characters,
        "has_audit_issue": has_audit_issue,
        "role_assignments": role_assignments,
        "audit_page": audit_page,
        "teamspeak3_user": teamspeak3_user,
    })


@login_required
@permission_required("hr.member_access")
@require_POST
def self_set_status(request):
    """Members set or clear a member_assignable status on themselves."""
    status = request.POST.get("status", "").strip()
    if status not in {v for v, _ in MemberStatusAssignment.STATUS_CHOICES}:
        messages.error(request, "Invalid status.")
        return redirect("hr:me")

    if status == MemberStatusAssignment.ACTIVE:
        clear_member_status(request.user, set_by=request.user, notes="Self-cleared via member dashboard")
        messages.success(request, "Your status has been cleared.")
    else:
        set_member_status(request.user, status=status, set_by=request.user, notes="")
        messages.success(request, f"Your status has been set to '{dict(MemberStatusAssignment.STATUS_CHOICES)[status]}'.")

    return redirect("hr:me")


@login_required
@permission_required("hr.member_access")
@require_POST
def self_assign_label(request, label_id):
    """Members toggle a member_assignable label on themselves."""
    label = get_object_or_404(MemberLabel, pk=label_id, is_active=True, member_assignable=True)
    action = request.POST.get("action", "").strip()

    if action == "assign":
        assign_label(request.user, label=label, assigned_by=request.user, notes="")
        messages.success(request, f"'{label}' added.")
    elif action == "remove":
        remove_label(request.user, label=label, performed_by=request.user, notes="Self-removed via member dashboard")
        messages.success(request, f"'{label}' removed.")
    else:
        messages.error(request, "Invalid action.")

    return redirect("hr:me")


# ---------------------------------------------------------------------------
# Member labels
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
@require_POST
def set_label(request, user_id):
    if not (_has_any_role(request.user) or request.user.is_superuser):
        return HttpResponseForbidden("You do not have an HR role.")

    member_user = get_object_or_404(User, pk=user_id)
    action = request.POST.get("action", "").strip()
    label_id = request.POST.get("label_id", "").strip()
    notes = request.POST.get("notes", "").strip()

    if not label_id.isdigit():
        messages.error(request, "Invalid label.")
        return redirect("hr:member_detail", user_id=user_id)

    label = get_object_or_404(MemberLabel, pk=int(label_id), is_active=True)

    if action == "assign":
        assign_label(member_user, label=label, assigned_by=request.user, notes=notes)
        messages.success(request, f"Label '{label}' assigned to {member_user}.")
    elif action == "remove":
        removed = remove_label(member_user, label=label, performed_by=request.user, notes=notes)
        if removed:
            messages.success(request, f"Label '{label}' removed from {member_user}.")
        else:
            messages.info(request, f"{member_user} did not have label '{label}'.")
    else:
        messages.error(request, "Invalid action.")

    return redirect("hr:member_detail", user_id=user_id)


# ---------------------------------------------------------------------------
# Role management
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.manage_roles")
@require_POST
def set_role(request, user_id):
    member_user = get_object_or_404(User, pk=user_id)
    action = request.POST.get("action", "").strip()

    if action == "add":
        role_id = request.POST.get("role_id", "").strip()
        if role_id.isdigit():
            role = get_object_or_404(Role, pk=int(role_id))
            _, created = assign_role(member_user, role, assigned_by=request.user)
            if created:
                messages.success(request, f"Role '{role}' assigned to {member_user}.")
            else:
                messages.info(request, f"{member_user} already holds role '{role}'.")
        else:
            messages.error(request, "Invalid role.")
    elif action == "remove":
        assignment_id = request.POST.get("assignment_id", "").strip()
        if assignment_id.isdigit():
            assignment = get_object_or_404(RoleAssignment, pk=int(assignment_id), user=member_user)
            remove_role(member_user, assignment.role, performed_by=request.user)
            messages.success(request, "Role removed.")
        else:
            messages.error(request, "Invalid assignment.")
    else:
        messages.error(request, "Invalid action.")

    return redirect("hr:member_detail", user_id=user_id)



# ---------------------------------------------------------------------------
# Unregistered characters
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
def unregistered(request):
    config = HrConfiguration.get_solo()

    if not config.aa_state:
        return render(request, "hr/unregistered.html", {"characters": [], "state": None})

    characters = _unregistered_chars_qs(config.aa_state).prefetch_related(
        "characteraudit__characterroles__titles"
    ).order_by("corporation_name", "character_name")

    search = request.GET.get("search", "").strip()
    if search:
        characters = characters.filter(character_name__icontains=search)

    paginator = Paginator(characters, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "hr/unregistered.html", {
        "state": config.aa_state,
        "page_obj": page_obj,
        "total": paginator.count,
        "search": search,
    })


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
def audit(request):
    entries = AuditLog.objects.select_related(
        "user__profile__main_character",
        "performed_by__profile__main_character",
        "old_rank", "new_rank",
        "label",
    )

    search = request.GET.get("search", "").strip()
    if search:
        entries = entries.filter(
            user__profile__main_character__character_name__icontains=search
        )

    action_filter = request.GET.get("action", "").strip()
    if action_filter:
        entries = entries.filter(action=action_filter)

    paginator = Paginator(entries, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "hr/audit.html", {
        "page_obj": page_obj,
        "search": search,
        "action_filter": action_filter,
        "action_choices": AuditLog.ACTION_CHOICES,
    })


# ---------------------------------------------------------------------------
# Dashboard snooze
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
@require_POST
def snooze_warning(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)
    note = request.POST.get("note", "").strip()
    expires_date = request.POST.get("expires_at", "").strip()

    if not note:
        messages.error(request, "A note is required when snoozing warnings.")
        return redirect("hr:member_detail", user_id=user_id)

    expires_at = None
    if expires_date:
        try:
            d = datetime.strptime(expires_date, "%Y-%m-%d").date()
            expires_at = timezone.make_aware(datetime.combine(d, dt_time.max))
        except ValueError:
            messages.error(request, "Invalid expiry date.")
            return redirect("hr:member_detail", user_id=user_id)

    DashboardSnooze.objects.update_or_create(
        user=target_user,
        defaults={
            "snoozed_by": request.user,
            "note": note,
            "expires_at": expires_at,
        },
    )
    messages.success(request, f"Warnings for {target_user} snoozed.")
    return redirect("hr:index")


@login_required
@permission_required("hr.access_hr")
@require_POST
def clear_snooze(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)
    DashboardSnooze.objects.filter(user=target_user).delete()
    messages.success(request, f"Snooze cleared for {target_user}.")
    return redirect("hr:index")
