# HR App — Rank Management Plan

## Overview

The HR app replaces codex entirely. It is the single source of truth for a
member's rank. HR assigns a rank to a user account. That rank drives:

1. AllianceAuth **group** membership — granted on assign, revoked on remove.
2. In-game **title** verification — all characters owned by that user (who are
   in the configured AA state) should carry the matching EVE title.

The verification is read-only from corptools (`CharacterRoles.titles`). No ESI
write tokens are needed. Title changes in-game are applied manually by a director
and confirmed when corptools next syncs.

---

## Configuration

`HrConfiguration` (singleton via `solo`):

| Field | Description |
|---|---|
| `aa_state` | FK → `allianceauth.authentication.models.State` — only users in this state are in scope for the member list and title sync |

---

## Models

### Rank

| Field | Type | Notes |
|---|---|---|
| `name` | CharField | Display name, e.g. "R1 – Recruit" |
| `priority` | PositiveIntegerField | Lower = more junior; used for ordering |
| `auth_group` | FK → `Group` | Granted on assign, revoked on remove |
| `eve_title` | CharField | Exact EVE title string to check against corptools |
| `description` | TextField (blank) | Optional internal notes |
| `is_active` | BooleanField | Inactive ranks cannot be assigned |

One rank per user at a time. Ranks are mutually exclusive.

---

### RankAssignment

Records the current (and historical) rank for each user.

| Field | Type | Notes |
|---|---|---|
| `user` | FK → User | The member |
| `rank` | FK → Rank | |
| `assigned_by` | FK → User (null) | Null for admin/system changes |
| `assigned_at` | DateTimeField (auto) | |
| `notes` | TextField (blank) | Reason for assignment |
| `is_current` | BooleanField | Only one `is_current=True` per user |

**On assignment** (service layer, wrapped in `transaction.atomic`):

1. Mark any existing `is_current=True` assignment as `is_current=False`.
2. Remove the old rank's `auth_group` from the user.
3. Create new `RankAssignment(is_current=True)`.
4. Add the new rank's `auth_group` to the user.
5. Write a `RankAuditLog` entry.

**On rank removal** (clearing a rank):

1. Mark current assignment `is_current=False`.
2. Remove the `auth_group`.
3. Write a `RankAuditLog` entry.

Group management is driven by the service layer (not signals) to keep the logic
explicit and transactional.

---

### HrRole

Defines what an HR operator is permitted to do with ranks.

| Field | Type | Notes |
|---|---|---|
| `name` | CharField | e.g. "Recruiter", "HR Officer", "HR Director" |
| `can_assign` | M2M → Rank | Ranks this role may grant |
| `can_remove` | M2M → Rank | Ranks this role may revoke |
| `description` | TextField (blank) | |

---

### HrRoleAssignment

| Field | Type | Notes |
|---|---|---|
| `user` | FK → User | |
| `hr_role` | FK → HrRole | |
| `assigned_by` | FK → User (null) | |
| `assigned_at` | DateTimeField (auto) | |

A user may hold multiple HR roles. Effective `can_assign` / `can_remove` sets are
the union across all their assigned roles.

Permission to *manage* HR role assignments is a standard Django permission:
`hr.manage_hr_roles`.

---

### RankAuditLog

Immutable log of all rank changes.

| Field | Type | Notes |
|---|---|---|
| `timestamp` | DateTimeField (auto) | |
| `action` | CharField (choices) | `assigned`, `removed`, `changed` |
| `user` | FK → User | The member acted on |
| `performed_by` | FK → User (null) | The HR operator |
| `old_rank` | FK → Rank (null) | |
| `new_rank` | FK → Rank (null) | |
| `notes` | TextField (blank) | |

---

## Title Sync

No background task or cached table. A character is in sync when
`char.characteraudit.characterroles.titles` contains a `CharacterTitle` whose
`title` matches `rank.eve_title`. This is resolved via `prefetch_related` on the
member list queryset — no N+1 queries, no extra model.

---

## Permissions

| Permission | Purpose |
|---|---|
| `hr.access_hr` | Can access the HR module |
| `hr.manage_ranks` | Can create/edit Rank definitions |
| `hr.manage_hr_roles` | Can assign HR roles to users |

Operational rank assign/remove permissions are derived from `HrRoleAssignment`,
not from raw Django permissions — a user may only act on ranks listed in their
effective `can_assign` / `can_remove` sets.

---

## UI Pages

### `/hr/` — Dashboard
- Summary counts: total members, out-of-sync titles, members without a rank.
- Issue list: members with title mismatches, surfaced for quick action.
- Visible to any user with `hr.access_hr`.

### `/hr/members/` — Member List
- All users in `config.aa_state` with their current rank and title sync state.
- Sortable/filterable by rank, character name, sync status.
- Visible to any user with `hr.access_hr`.

### `/hr/user/<user_id>/` — Member Detail / Rank Assignment
- Shows current rank, full assignment history, and per-character title sync status.
- Rank dropdown filtered to ranks the logged-in HR user may assign/remove.
- Notes field. Confirm before submitting.

### `/hr/roles/` — HR Role Management
- Assign/remove HR roles from users.
- Gated by `hr.manage_hr_roles`.

### `/hr/ranks/` — Rank Definitions
- CRUD for Rank objects (name, priority, group, eve_title, is_active).
- Gated by `hr.manage_ranks`.

### `/hr/audit/` — Audit Log
- Read-only log of all rank changes.
- Filterable by user, actor, rank, date range.
- Visible to any user with `hr.access_hr`.

---

## Models Summary

```python
HrConfiguration(SingletonModel)
    aa_state -> State

Rank
    name, priority, auth_group -> Group, eve_title, description, is_active

RankAssignment
    user -> User, rank -> Rank, assigned_by -> User|null,
    assigned_at, notes, is_current

HrRole
    name, can_assign M2M Rank, can_remove M2M Rank, description

HrRoleAssignment
    user -> User, hr_role -> HrRole, assigned_by -> User|null, assigned_at


RankAuditLog
    timestamp, action, user -> User, performed_by -> User|null,
    old_rank -> Rank|null, new_rank -> Rank|null, notes
```

---

## Replacing Codex — Features to Decide

Codex includes several features beyond rank management. Confirm which carry over
to HR and which are dropped:

| Codex Feature | Description | Decision needed |
|---|---|---|
| **Member notes** | Free-text notes on a member by HR staff | Carry over to HR? |
| **Tags** (non-rank) | Stackable labels e.g. "On Leave", "Suspect" | Carry over to HR? |
| **Reviews** | Rank review due after N days of service; acknowledgement workflow | Carry over to HR? |
| **Checklists** | Per-tag checklist items completed by HR | Carry over to HR? |
| **Former members** | Tracks users who had a rank but are no longer in state | Carry over to HR? |
| **Service length** | Days in corp calculated from corptools CorporationHistory | Display on member list? |

The rank mismatch / title sync display from codex's dashboard and member list is
fully covered by the HR sync design above.
