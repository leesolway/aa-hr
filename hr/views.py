from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from allianceauth.eveonline.models import EveCharacter

from .models import HrConfiguration, Role, RoleAssignment, Rank, RankAuditLog
from .services import (
    assign_rank,
    characters_missing_title,
    get_current_rank,
    get_effective_assignable_ranks,
    get_effective_removable_rank_ids,
    prepare_members,
    remove_rank,
)

User = get_user_model()


def _has_any_role(user):
    return user.role_assignments.exists()


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

    total = len(members)
    no_rank = sum(1 for m in members if not m["rank"])
    mismatches = sum(1 for m in members if m["title_mismatch"])
    audit_issues = sum(1 for m in members if m["has_audit_issue"])

    issue_members = [m for m in members if m["title_mismatch"] or not m["rank"] or m["has_audit_issue"]]

    corp_ids = list(
        config.aa_state.member_corporations.values_list("corporation_id", flat=True)
    )
    alliance_ids = list(
        config.aa_state.member_alliances.values_list("alliance_id", flat=True)
    )
    unregistered_count = (
        EveCharacter.objects.filter(
            Q(corporation_id__in=corp_ids) | Q(alliance_id__in=alliance_ids)
        )
        .filter(character_ownership__isnull=True)
        .count()
    )

    return render(request, "hr/dashboard.html", {
        "state": config.aa_state,
        "total_members": total,
        "no_rank": no_rank,
        "title_mismatches": mismatches,
        "audit_issues": audit_issues,
        "issue_members": issue_members,
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
    member_user = get_object_or_404(
        User.objects.select_related("profile__main_character").prefetch_related(
            "character_ownerships__character__characteraudit__characterroles__titles",
            "hr_rank_assignments__rank__auth_group",
            "hr_rank_assignments__assigned_by__profile__main_character",
        ),
        pk=user_id,
    )

    current_assignment = next(
        (a for a in member_user.hr_rank_assignments.all() if a.is_current), None
    )
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

    missing_title_chars = []
    if current_rank:
        missing_title_chars = characters_missing_title(member_user, current_rank)

    history = [a for a in member_user.hr_rank_assignments.all() if not a.is_current]

    main = getattr(member_user.profile, "main_character", None)
    alts = []
    if main:
        alts = [
            o.character
            for o in member_user.character_ownerships.all()
            if o.character and o.character.character_id != main.character_id
        ]

    audit_issue_chars = []
    for ownership in member_user.character_ownerships.all():
        char = ownership.character
        if not char:
            continue
        try:
            if not char.characteraudit.active:
                audit_issue_chars.append((char, "stale"))
        except AttributeError:
            audit_issue_chars.append((char, "missing"))

    try:
        teamspeak3_user = member_user.teamspeak3
    except Exception:
        teamspeak3_user = None

    return render(request, "hr/member_detail.html", {
        "member_user": member_user,
        "main": main,
        "alts": alts,
        "current_rank": current_rank,
        "current_assignment": current_assignment,
        "missing_title_chars": missing_title_chars,
        "assignable_ranks": assignable_ranks,
        "can_assign": can_assign,
        "can_remove": can_remove,
        "history": history,
        "audit_issue_chars": audit_issue_chars,
        "teamspeak3_user": teamspeak3_user,
    })


@login_required
@permission_required("hr.access_hr")
def set_rank(request, user_id):
    if request.method != "POST":
        return redirect("hr:member_detail", user_id=user_id)

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
# Role management
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.manage_roles")
def roles(request):
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add":
            user_id = request.POST.get("user_id", "").strip()
            role_id = request.POST.get("role_id", "").strip()
            if user_id.isdigit() and role_id.isdigit():
                target_user = get_object_or_404(User, pk=int(user_id))
                role = get_object_or_404(Role, pk=int(role_id))
                RoleAssignment.objects.get_or_create(
                    user=target_user,
                    role=role,
                    defaults={"assigned_by": request.user},
                )
                messages.success(request, f"Assigned {role} to {target_user}.")
            else:
                messages.error(request, "Invalid user or role.")

        elif action == "remove":
            assignment_id = request.POST.get("assignment_id", "").strip()
            if assignment_id.isdigit():
                RoleAssignment.objects.filter(pk=int(assignment_id)).delete()
                messages.success(request, "Role removed.")

        return redirect("hr:roles")

    assignments = (
        RoleAssignment.objects.select_related(
            "user__profile__main_character",
            "role",
            "assigned_by__profile__main_character",
        )
        .order_by("role__name", "user__profile__main_character__character_name")
    )
    all_roles = Role.objects.all()
    all_users = (
        User.objects.select_related("profile__main_character")
        .filter(profile__isnull=False)
        .order_by("profile__main_character__character_name")
    )

    return render(request, "hr/roles.html", {
        "assignments": assignments,
        "all_roles": all_roles,
        "all_users": all_users,
    })


# ---------------------------------------------------------------------------
# Unregistered characters
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
def unregistered(request):
    config = HrConfiguration.get_solo()

    if not config.aa_state:
        return render(request, "hr/unregistered.html", {"characters": [], "state": None})

    corp_ids = list(
        config.aa_state.member_corporations.values_list("corporation_id", flat=True)
    )
    alliance_ids = list(
        config.aa_state.member_alliances.values_list("alliance_id", flat=True)
    )

    characters = (
        EveCharacter.objects.filter(
            Q(corporation_id__in=corp_ids) | Q(alliance_id__in=alliance_ids)
        )
        .filter(character_ownership__isnull=True)
        .order_by("corporation_name", "character_name")
    )

    search = request.GET.get("search", "").strip()
    if search:
        characters = characters.filter(character_name__icontains=search)

    paginator = Paginator(characters, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "hr/unregistered.html", {
        "state": config.aa_state,
        "page_obj": page_obj,
        "total": characters.count(),
        "search": search,
    })


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@login_required
@permission_required("hr.access_hr")
def audit(request):
    entries = RankAuditLog.objects.select_related(
        "user__profile__main_character",
        "performed_by__profile__main_character",
        "old_rank",
        "new_rank",
    )

    search = request.GET.get("search", "").strip()
    if search:
        entries = entries.filter(
            user__profile__main_character__character_name__icontains=search
        )

    paginator = Paginator(entries, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "hr/audit.html", {
        "page_obj": page_obj,
        "search": search,
    })
