# HR Module

Human-Resources management for AllianceAuth. Tracks member rank, status, and labels; enforces EVE title synchronisation; and provides an issue dashboard for HR operators.

## Features

- Rank assignment with full audit trail
- Member status (Away / Break) with optional rank removal on Break
- Member labels (non-exclusive tags, optionally self-assignable)
- HR operator roles with per-rank assign/remove rights
- EVE in-game title sync check (read-only via corptools)
- Dashboard issue list with per-member snooze
- Unregistered character tracking
- Group-sync signal: external AA group removal auto-cleans HR assignments
- State-loss signal: rank/role/label/status cleared when user leaves the configured AA state

## Permissions

| Permission | Codename | Who needs it |
|---|---|---|
| Module access | `hr.access_hr` | All HR operators. Grants access to the dashboard, member list, member detail, unregistered list, and audit log. Menu item is hidden without this permission. |
| Member self-service | `hr.member_access` | Regular members. Grants access to `/hr/me/` where they can view their own rank/status and toggle self-assignable labels. |
| Manage ranks | `hr.manage_ranks` | Admins only. Unlocks rank/label/status definition CRUD in the Django admin panel. No UI in the HR app itself. |
| Manage roles | `hr.manage_roles` | HR admins. Unlocks the Roles panel on the member detail page (`/hr/user/<id>/`), allowing HR role assignment and removal. |

> **Operational assign/remove rights** (which ranks an operator may assign or remove) come from `RoleAssignment`, not Django permissions. Superusers bypass all role checks and can assign any active rank.

## URL Structure

| URL | View | Required permission |
|---|---|---|
| `/hr/` | Dashboard | `access_hr` |
| `/hr/me/` | Member self-service dashboard | `member_access` |
| `/hr/me/label/<id>/` | Self-assign/remove label (POST) | `member_access` |
| `/hr/me/status/` | Self-set status (POST) | `member_access` |
| `/hr/members/` | Member list | `access_hr` |
| `/hr/user/<id>/` | Member detail | `access_hr` |
| `/hr/user/<id>/set-rank/` | Assign/remove rank (POST) | `access_hr` + role check |
| `/hr/user/<id>/set-status/` | Set member status (POST) | `access_hr` + any role |
| `/hr/user/<id>/set-label/` | Assign/remove label (POST) | `access_hr` + any role |
| `/hr/user/<id>/set-role/` | Assign/remove HR role (POST) | `manage_roles` |
| `/hr/user/<id>/fix/` | Sync HR groups (POST) | `access_hr` |
| `/hr/user/<id>/snooze/` | Snooze dashboard warnings (POST) | `access_hr` |
| `/hr/user/<id>/snooze/clear/` | Clear snooze (POST) | `access_hr` |
| `/hr/unregistered/` | Unregistered characters | `access_hr` |
| `/hr/audit/` | Audit log | `access_hr` |

## Setup

1. Add `"hr"` to `INSTALLED_APPS` in your AllianceAuth settings.
2. Run `python -m django migrate hr`.
3. Open the Django admin and configure `HrConfiguration`:
   - Set **AA State** to the state whose members should appear in the HR module.
   - Optionally set **Home Corp** to restrict the member list and title checks to a single corporation.
4. Create at least one `Rank` and one `Role` via the admin.
5. Grant `hr.access_hr` to your HR operators (via AA group or directly).
6. Grant `hr.member_access` to your member state group so members can use the self-service dashboard.

## Dependencies

- [corptools](https://github.com/pvyParts/allianceauth-corp-tools) — provides `CharacterAudit`, `CharacterRoles`, and `CharacterTitle` (read-only).
- [django-solo](https://github.com/lazybird/django-solo) — singleton configuration model.
- AllianceAuth core — `State`, `EveCharacter`, `CharacterOwnership`.
