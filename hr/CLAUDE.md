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
| `HrRole` | RBAC role for HR operators. `can_assign`/`can_remove` M2M → Rank |
| `HrRoleAssignment` | Links a user to an `HrRole`. User can hold multiple roles. |
| `RankAuditLog` | Immutable log. Written by service layer only. |

One rank per user at a time (enforced in service layer, not DB constraint).

### Service Layer (`services.py`)

All rank mutations go through here — never manipulate models directly from views.

- `assign_rank(user, rank, assigned_by, notes)` — atomic, swaps group, writes audit log
- `remove_rank(user, performed_by, notes)` — atomic, removes group, writes audit log
- `get_effective_assignable_ranks(user)` — union of can_assign across all HrRoles
- `get_effective_removable_rank_ids(user)` — union of can_remove PKs
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
| `hr.manage_ranks` | Rank definition CRUD (handled in Django admin) |
| `hr.manage_hr_roles` | HR role assignments page at `/hr/roles/` |

Operational assign/remove rights come from `HrRoleAssignment`, not Django perms.
Superusers bypass HR role checks and can assign any active rank.

### Views / URLs

| URL | View | Permission |
|---|---|---|
| `/hr/` | `dashboard` | `access_hr` |
| `/hr/members/` | `member_list` | `access_hr` |
| `/hr/user/<id>/` | `member_detail` | `access_hr` |
| `/hr/user/<id>/set-rank/` | `set_rank` (POST) | `access_hr` + HR role check |
| `/hr/roles/` | `roles` | `manage_hr_roles` |
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

## Codex Replacement Status

`codex` remains installed and functional until HR covers all needed features.
Open questions before codex can be removed (answer these to extend HR):
- Member notes (free-text HR notes per member)?
- Non-rank tags (e.g. "On Leave", "Suspect")?
- Service-length review workflow?
- Former member tracking?
