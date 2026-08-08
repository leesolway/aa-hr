# HR App — Claude Context

## Purpose

The HR app is the source of truth for member rank. It replaces the `codex` app
(currently still installed, to be removed once HR is feature-complete).

A rank assigned to a user account drives:
1. AllianceAuth group membership (granted/revoked atomically in the service layer)
2. EVE title verification — corptools is queried at render time via prefetch; no
   background task or cached table needed

---

## Project Environment

- Working directory: `/home/allianceauth/myauth`
- Settings module: `DJANGO_SETTINGS_MODULE=myauth.settings.local`
- Django check: `python -m django check hr`
- Migrations: `python -m django migrate hr`
- Database: MySQL (credentials via env vars)

Local apps installed in `myauth/settings/local.py`:
`corptools`, `codex` (retiring), `hr`, `isksync`, `logistica`, `opcalendar`

---

## AllianceAuth App Conventions

Every AA app needs:
- `apps.py` — `AppConfig` with `ready()` importing `auth_hooks`
- `auth_hooks.py` — registers `UrlHook` and `MenuItemHook` via `@hooks.register`
- `urls.py` — `app_name = "hr"` namespace
- `migrations/` — standard Django migrations

Menu item visibility is controlled by checking permissions in
`MenuItemHook.render()`. The base permission is `hr.access_hr`.

---

## HR App Architecture

### Models (`models.py`)

| Model | Purpose |
|---|---|
| `HrConfiguration` | Singleton (django-solo). Holds `aa_state` FK to `allianceauth.authentication.State`. |
| `Rank` | Definition: name, priority, `auth_group` (1:1 Group), `corp_title` (FK → `corptools.CharacterTitle`), `is_active` |
| `RankAssignment` | Per-user rank record. `is_current=True` = active rank. History kept by setting `is_current=False`. |
| `Role` | RBAC role for HR operators. `can_assign`/`can_remove` M2M → Rank |
| `RoleAssignment` | Links a user to a `Role`. User can hold multiple roles. |
| `MemberStatus` | Named status definition (e.g. Break). Has `auth_group`, `removes_rank`. |
| `MemberStatusAssignment` | Active status for a user (one at most). |
| `MemberStatusLog` | Immutable log of status changes. *(legacy — services write to `AuditLog` instead)* |
| `LabelCategory` | Groups `MemberLabel`s for display. Has `display_order`. |
| `MemberLabel` | Non-exclusive tag. Optional `auth_group`, `member_assignable` flag, `is_active`. |
| `MemberLabelAssignment` | Active label on a user. Multiple per user allowed. |
| `MemberLabelLog` | Immutable log of label assign/remove actions. *(legacy — services write to `AuditLog` instead)* |
| `AuditLog` | Unified immutable audit log. Covers rank, status, label, and role-clear actions. Written by service layer only. |

One rank per user at a time (enforced in service layer, not DB constraint).

### Service Layer (`services.py`)

All rank mutations go through here — never manipulate models directly from views.

- `get_current_rank(user)` — return current `RankAssignment` or None
- `assign_rank(user, rank, assigned_by, notes)` — atomic, swaps group, writes audit log
- `remove_rank(user, performed_by, notes)` — atomic, removes group, writes audit log
- `get_effective_assignable_ranks(user)` — union of can_assign across all Roles
- `get_effective_removable_rank_ids(user)` — union of can_remove PKs
- `set_member_status(user, status, set_by, notes)` — atomic; swaps group, removes rank and clears all `RoleAssignment`s if `removes_rank`
- `clear_member_status(user, set_by, notes)` — clears active status; returns False if none set
- `assign_label(user, label, assigned_by, notes)` — idempotent; adds AA group, writes log
- `remove_label(user, label, performed_by, notes)` — removes label and AA group; returns True/False
- `prepare_members(config)` — bulk queryset with prefetch for member list
- `characters_missing_title(user, rank)` — live corptools lookup, no cache

### Title Sync

No background task. Title sync is a live DB lookup:
```python
char.characteraudit.characterroles.titles.all()
```
Compare `.title` string against `rank.corp_title.title`. Uses `prefetch_related` in
`prepare_members` to avoid N+1. corptools is the data source (read-only).

### Permissions

| Permission | Usage |
|---|---|
| `hr.access_hr` | Module access, menu visibility |
| `hr.member_access` | Member self-service dashboard at `/hr/me/` |
| `hr.manage_ranks` | Rank definition CRUD (handled in Django admin) |
| `hr.manage_roles` | Unlocks role management panel on member detail page (`/hr/user/<id>/`) |

Operational assign/remove rights come from `RoleAssignment`, not Django perms.
Superusers bypass HR role checks and can assign any active rank.

### Views / URLs

| URL | View | Permission |
|---|---|---|
| `/hr/` | `dashboard` | `access_hr` |
| `/hr/me/` | `member_dashboard` | `member_access` |
| `/hr/me/label/<id>/` | `self_assign_label` (POST) | `member_access` |
| `/hr/me/status/` | `self_set_status` (POST) | `member_access` |
| `/hr/members/` | `member_list` | `access_hr` |
| `/hr/user/<id>/` | `member_detail` | `access_hr` |
| `/hr/user/<id>/set-rank/` | `set_rank` (POST) | `access_hr` + role check |
| `/hr/user/<id>/set-status/` | `set_status` (POST) | `access_hr` + has_any_role |
| `/hr/user/<id>/set-label/` | `set_label` (POST) | `access_hr` + has_any_role |
| `/hr/user/<id>/set-role/` | `set_role` (POST) | `manage_roles` |
| `/hr/unregistered/` | `unregistered` | `access_hr` |
| `/hr/audit/` | `audit` | `access_hr` |

### Templates

All extend `hr/base.html` → block `hr_content`.
Load `{% load i18n hr_tags %}` — `hr_tags` provides `eve_image`, `zkillboard_url`, `evewho_url`.

---

## corptools Integration

Key models used (read-only):
- `corptools.models.CharacterTitle` — `title_id`, `title`, `corporation_id`
- `corptools.models.CharacterRoles` — `character` (1:1 CharacterAudit), `titles` (M2M CharacterTitle)
- `corptools.models.CharacterAudit` — linked via `EveCharacter.characteraudit`

Prefetch pattern for member list:
```python
.prefetch_related(
    "character_ownerships__character__characteraudit__characterroles__titles"
)
```

---

## Key Dependencies

- `django-solo` — `SingletonModel` for `HrConfiguration` (`get_solo()` pattern)
- `allianceauth.authentication.models.State` — for `aa_state` config
- `allianceauth.authentication.models.CharacterOwnership` — owned characters
- `allianceauth.eveonline.models.EveCharacter` — character data

---

## Member Status & Labels

- Status is exclusive (one per user). Absence of a `MemberStatusAssignment` = normal/active.
- Labels are non-exclusive (many per user). `MemberLabel.member_assignable` allows self-service via `/hr/me/`.
- **Group sync signal** in `signals.py` (`sync_group_removal`): AA group removals triggered externally auto-clean matching `MemberLabelAssignment` and `MemberStatusAssignment`.
- **Title mismatch suppression**: `prepare_members` sets `title_mismatch=False` for any member on an active status (not actionable). `is_on_break=True` when `status.removes_rank=True` — dashboard excludes these from `no_rank` count and `issue_members`.

## Codex Replacement Status

`codex` remains installed and functional until HR covers all needed features.
Open questions before codex can be removed (answer these to extend HR):
- Member notes (free-text HR notes per member)?
- ~~Non-rank tags~~ — covered by `MemberLabel`/`LabelCategory`
- Service-length review workflow?
- Former member tracking?
