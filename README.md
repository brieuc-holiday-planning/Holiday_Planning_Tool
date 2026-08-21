# Holiday Planning Tool

Internal Django app for planning and approving time off across a
Tribe → Cluster → Squad organisation.

- **Squad calendar** — who's away, sprints, bank holidays and events; click days to request time off (full or 1/2 day).
- **Per-day approval** — a Chapter Lead approves or refuses each day individually, with a required justification on refusal.
- **Metrics** — quarterly worked and absence days per member against an annual worked-days cap.
- **Admin** — admins manage people, org structure, titles, sprints, bank holidays and events.

## Quick start

```bash
./app.sh setup       # venv + dependencies + .env (with a generated SECRET_KEY) + migrations
./app.sh bootstrap   # create the tribe and the break-glass admin account
./app.sh dev         # http://127.0.0.1:8000
```

`./app.sh help` lists every command.

---

# Business rules

Every rule the application enforces, grouped by area. Each one is covered by
a test; the file listed after each heading is where the rule lives.

## 1. Organisation structure

`apps/org/models.py`

1. The hierarchy is **Tribe → Cluster → Squad**. A squad reaches its tribe through its cluster.
2. Cluster names are unique within a tribe; squad names are unique within a cluster.
3. **Titles** (job functions, e.g. Data Scientist) are defined per tribe and managed in the admin — they are not a fixed list. Both the name and the short abbreviation are unique within a tribe.
4. A title that is in use cannot be deleted (users reference it with `PROTECT`).
5. **Squad watchers** are plain email addresses attached to a squad — they need no account. An address may appear once per squad.

## 2. People, roles and admin access

`apps/accounts/models.py`, `apps/core/admin.py`

6. There are exactly two roles: **Chapter Lead** and **End User**. There is deliberately **no Scrum Master role** — `role` governs the approval workflow only.
7. **Admin access is granted by title, not by role.** Anyone holding a title marked *grants admin access* becomes an admin of the app (`User.is_scrum_master`), whatever their role. This means a Chapter Lead or an End User can be an admin without changing how their own requests are routed.
8. `is_staff` is derived, never set by hand. It is true when the user is a superuser, **or** holds an admin-granting title, **or** holds the silent-edit permission. It is recomputed in both directions when a user is saved in the admin, and for every holder of a title when that title's admin flag is toggled.
9. **A squad is required for everyone except** Chapter Leads (who approve tribe-wide by title) and admin-title holders (who manage the tribe). Both may still belong to a squad.
10. **At most one Chapter Lead per title**, enforced by a partial unique DB constraint. Attempting a second one is rejected with a form error, not a crash.
11. Only one genuine Django superuser should exist — the break-glass account created by `bootstrap_tribe`. Admins created afterwards are `is_superuser=False` and cannot self-escalate: the admin form hides `is_superuser`, `groups` and `user_permissions` from non-superusers.

## 3. Approval routing

`apps/holidays/services.py`

12. **Requests route by title, not by squad.** The approver for a request is whoever holds role *Chapter Lead* and the **same title** as the requester — regardless of which squad either belongs to.
13. Assigning role *Chapter Lead* + a title **is** the entire mechanism for becoming that title's approver. There is no separate assignment step.
14. **Fallback:** if a title has no Chapter Lead, or the resolved lead would be the requester themselves, the request routes to the first active admin-title holder other than the requester.
15. The approver is **snapshotted on the request at submission time**, so history stays stable if routing later changes.
16. **In-flight requests follow a reassignment.** When a title's Chapter Lead changes, every request with at least one still-pending day from a user with that title is re-routed. Already-decided days are never touched — their decision is history.
17. **Backup approvers** (*Backup chapter lead assignments*) stand in when the primary is away. Any user is eligible regardless of role, a title may have several, and the same person can back up several titles. Each `(tribe, title, backup)` combination is unique, and the title must belong to the same tribe.
18. A user can act on a request if they are its routed approver **or** a designated backup for the requester's title.

## 4. Requesting time off

`apps/holidays/services.py::submit_request`

19. A request covers one or more days; each day is a **full day (1.0)** or a **1/2 day (0.5)**. "1/2 day" is the wording used throughout the interface.
20. You may only submit for **your own squad**. Other squads' calendars are viewable but read-only.
21. A request must contain **at least one day**.
22. A date may appear **only once** in a request.
23. **Dates in the past cannot be requested** — today is the earliest bookable day.
24. **Weekends cannot be requested** — nobody works them.
25. **Bank holidays cannot be requested.**
26. **A day holds 1.0 units**, where a full day is 1.0 and a 1/2 day is 0.5. A new request is rejected if it would take a date past 1.0. So a 1/2 day can be added on top of an existing 1/2 day, but nothing can be added to a full day, and a full day cannot be added to a 1/2 day. Pending days consume capacity too; refused and cancelled ones release it.
27. Validation is all-or-nothing: if any day fails, nothing is created.

## 5. Deciding requests

`apps/holidays/services.py`, `apps/holidays/views.py`

28. **Approval is per day, not per request** — a multi-day submission can end up partly approved and partly refused.
29. Only a **pending** day can be approved or refused; a decided day is final through this route.
30. Only the routed approver or a designated backup may decide (rule 18).
31. **Refusal requires a non-empty justification.** Approval requires nothing.
32. Every decision records who made it and when.
33. The approval inbox shows only days belonging to titles the viewer can approve for, and can be filtered to a single requester. The decided list is the complete history, paged, and the filter is carried through pagination and across a decision.
34. A **red badge** on the nav shows how many days are awaiting this approver's decision.

## 6. Cancelling your own time off

`apps/holidays/services.py::cancel_own_day`

35. A requester may **cancel their own pending or approved days**. Nobody else's, and a refused or already-cancelled day cannot be cancelled again.
36. Cancelling an **approved** day emails the routed Chapter Lead, since they had planned cover around it. Cancelling a **pending** day notifies nobody — it was never granted.
37. A cancelled day is kept as `CANCELLED` rather than deleted: it leaves the calendar and the metrics as if it never happened, **frees the date to be requested again**, and stays in the Chapter Lead's decision board as an audit trail.

## 7. Direct edit — the "silently edit any holiday request" permission

`apps/holidays/services.py::silently_set_day_status`

A narrowly-scoped power for someone who keeps a squad's calendar accurate
(e.g. recording an unplanned absence). Granted per user in the admin.

38. The holder may only edit members of **their own squad**.
39. **A Chapter Lead's holiday can never be edited this way** — enforced server-side, and Chapter Leads are not offered in the member picker.
40. Only two actions exist: **add** a full or 1/2 day, or **cancel** an existing one. Nothing else can be set.
41. **A comment is always required.**
42. Weekends and bank holidays cannot be added (same as rules 24–25).
43. **Cancel requires an existing pending or approved day** on that date; there is nothing to cancel otherwise.
44. An added day is recorded as **approved immediately**, stamped with the editor as the decider — it bypasses the approval workflow.
45. Adding to a date that already has a pending/approved day **updates that day in place** rather than creating a conflicting second row.
46. A cancelled day gets the distinct **Cancelled** status: excluded from the calendar and from metrics as if it never existed, but the row and its comment are kept for audit.
47. This is *not* silent to the chapter lead: every change **emails a recap** to the routed Chapter Lead and appears in their approval inbox under *Recently decided*, attributed to the editor.

## 8. Squad calendar

`apps/holidays/services.py::calendar_feed_events`

48. **Weekends are hidden entirely** — no Saturday or Sunday columns.
49. Only **pending and approved** absences appear. Refused and cancelled days do not.
50. **Any authenticated user may view any squad's calendar** across the whole tribe. Only *submitting* is restricted to your own squad.
51. Each day shows a **per-title working count** (`AI 1/1 · DS 3.5/4`). Only **approved** absences reduce it — a pending request isn't confirmed yet — and a 1/2 day removes half a person, so three of four present plus one on a 1/2 day reads `3.5/4`. Under-staffed titles are highlighted.
52. Sprints render as background bands labelled `Q3SP4`, split so they **never cover a weekend**.
53. Events are informational and appear at tribe, cluster or squad scope depending on their own scope.

## 9. Sprints

`apps/calendar_data/models.py`, `apps/calendar_data/services.py`

54. Sprints are **only ever created a whole quarter at a time** through *Generate sprints for a quarter*. Manual "add" is disabled in the admin.
55. A sprint is always **Monday of week N to Friday of week N+1** — 10 working days.
56. The range must **start on a Monday** and **end on a Friday**, with the end after the start.
57. The range must divide into **whole 2-week blocks** (an even number of weeks).
58. A quarter may contain **at most 8 sprints**.
59. Only **one batch per (tribe, year, quarter)** — regenerating requires deleting the existing batch first.
60. **Sprints may never overlap.** A requested range must be clear of *every* existing sprint in the tribe, not just the quarter being generated. The error names the sprints to delete.
61. The same rule applies when **editing** an existing sprint — you cannot stretch one over its neighbour.
62. Sprints are named **SP1…SPn, restarting each quarter**; the name is unique within `(tribe, year, quarter)`. They display as `Q{quarter}SP{n}`.
63. Generation is all-or-nothing — a validation failure creates nothing.
64. The year picker offers **the current year, then next, then previous**, defaulting to the current one.

## 10. Bank holidays and events

`apps/calendar_data/models.py`

65. A bank holiday is **one per date per tribe**.
66. Bank holidays are excluded from worked-day metrics and cannot be booked as leave.
67. An event's scope must match its foreign keys exactly: tribe-scoped sets neither cluster nor squad; cluster-scoped sets cluster only; squad-scoped sets squad. Enforced by both a DB constraint and form validation.
68. An event's end date cannot precede its start date.
69. **Events are purely informational** — they never affect metrics or block requests.

## 11. Metrics

`apps/dashboard/services.py`

70. Metrics are computed per member per quarter for a calendar year.
71. **Absence days** count **approved days only** — pending, refused and cancelled days are excluded. A 1/2 day counts 0.5.
72. **Worked days** = weekdays in the quarter − weekday bank holidays − approved absences. Weekends never count.
73. **YTD worked** is compared against `ANNUAL_WORKED_DAYS_CAP` (default **220**, configurable by env).
74. The cap applies to **worked** days, not absence days — exceeding it means the member is on track to work more than their contractual maximum and should take more time off.
75. Metrics are **visible tribe-wide** to any authenticated user; there is no write action to restrict.

## 12. Notifications

`apps/core/emails.py`

76. **Request submitted** → the routed Chapter Lead (with an action link) **and** every squad watcher (FYI, no login-gated link).
77. **Day approved / refused** → the requester; the refusal email includes the justification.
78. **Approved day cancelled by the requester** → the routed Chapter Lead, so they can re-plan the cover they had arranged. Cancelling a *pending* day notifies nobody.
79. **Direct edit** → the routed Chapter Lead, with a recap of the days changed and the comment.
80. Email is sent **only after the database transaction commits**, so a rolled-back operation never sends a stray notification.
81. Recipients without an email address are skipped rather than erroring.

## Known gaps

Two behaviours are deliberate as-implemented but are worth a decision:

- **"YTD worked" counts the whole year, not year-to-date.** Weekdays are counted for all four quarters regardless of whether they have happened, so a member shows ~260 worked days against a 220 cap from January onwards, and the cap indicator reads over-cap all year. If it should count only up to today, `_weekdays_in_quarter` is where to change it.
- **A Chapter Lead sees their own request in their own inbox.** Their title is in their own approvable set, so their leave (routed to the fallback admin per rule 14) appears with Approve/Refuse buttons that will fail validation if used.

---

## Deploying

```bash
./app.sh deploy      # migrate + collectstatic + Django's --deploy checks
./app.sh prod        # gunicorn on $HOST:$PORT (WEB_CONCURRENCY workers)
```

Set these in the environment (or `.env`) first:

| Variable | Notes |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` |
| `DJANGO_SECRET_KEY` | **required** — prod refuses to start on the placeholder |
| `DJANGO_ALLOWED_HOSTS` | your hostname(s), comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | e.g. `https://holidays.example.com` — POSTs fail CSRF behind a proxy without it |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | notifications; dev prints to the console instead |
| `ANNUAL_WORKED_DAYS_CAP` | defaults to 220 |

Static files are served by WhiteNoise from the app process — no nginx or CDN
required. HTTPS redirect, secure cookies and HSTS are **on by default** in
production; the `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_SECURE_COOKIES` and
`DJANGO_HSTS_SECONDS` variables exist only to relax them when exercising
prod settings locally over plain HTTP.

### Database

SQLite (`db.sqlite3`), which is **not** in version control. A deployment
starts with an empty database: run `./app.sh migrate` then
`./app.sh bootstrap`. Back the file up like any other data — it holds every
user and holiday record. For anything beyond a small team, point
`DATABASES` at Postgres.

## Tests

```bash
./app.sh test
```

232 tests covering the rules above: the request/approval workflow, routing
and backup approvers, sprint generation and overlap, metrics, notifications,
and RBAC across both the app and the admin.
