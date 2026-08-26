# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-08-26

### Added

- **Self-service cancellation.** A requester can cancel their own pending or
  approved days. Cancelling an approved day emails the routed Chapter Lead
  (they had planned cover around it); a pending one notifies nobody. The day
  is kept as `CANCELLED`, so it leaves the calendar and metrics, frees the
  date to be requested again, and stays in the decision board for audit.
- **Paged decision history.** The Chapter Lead's decided list is now the full
  history, paged 25 at a time, instead of the 20 most recent rows. The
  requester filter applies across the whole history and survives pagination.
- **Pending-count badge.** A red count of days awaiting decision sits on the
  nav's Approval inbox link, for Chapter Leads and backups alike.
- **Half-day rendering.** A 1/2 day is drawn as a half-width chip on the
  calendar, so partial absence is visible at a glance.

### Changed

- Holidays can no longer be requested **for dates in the past**.
- Overlap is measured in **units** rather than presence: a day holds 1.0, a
  full day is 1.0 and a 1/2 day 0.5, and a request is refused if it would
  take a date past 1.0. A 1/2 day can therefore be added on top of an
  existing 1/2 day, while nothing can be stacked on a full day.
- "Half day" is written **"1/2 day"** everywhere it is shown.
- Calendar chips read **"Name - 1/2 day"** rather than "Name (1/2 day)",
  which truncated to an unclosed bracket; the full label is also available
  as a hover tooltip.

### Fixed

- Deciding a day **no longer resets the inbox filters**. The decision forms
  carry the active filter and page, and a requester stays in the filter
  dropdown after their last pending day is decided.
- A 1/2 day now **deducts half a person** from the calendar's working count
  (`DS 3.5/4`); previously half days were ignored and counted as present.
- A multi-line `{# #}` comment rendered as visible text in the inbox's Note
  column — Django's `{# #}` is single-line only.

## [1.0.0] — 2026-08-21

First release. See the *Business rules* section of the README for the
rules the application enforces.

### Added

**Organisation**
- Tribe → Cluster → Squad hierarchy with per-tribe, admin-managed Titles.
- Squad watchers: plain email addresses cc'd on submissions, no account needed.

**People and access**
- Two roles — Chapter Lead and End User. Admin access is granted by *title*
  rather than role, so anyone can administer the tribe without changing how
  their own requests are routed.
- `is_staff` is derived (superuser, admin-granting title, or the silent-edit
  permission) and resynced in both directions.
- At most one Chapter Lead per title, enforced by a partial unique constraint.

**Requesting and approving**
- Squad calendar (FullCalendar, weekdays only) showing absences, sprints,
  bank holidays and events, with click-to-request full or half days.
- Validation on submission: no weekends, no bank holidays, no duplicate or
  overlapping dates, own squad only.
- Per-day approval — one submission can end up partly approved and partly
  refused. Refusal requires a justification.
- Approval routing by title rather than squad, snapshotted at submission,
  with a fallback approver and automatic re-routing of in-flight requests
  when a title's Chapter Lead changes.
- Backup approvers: any user, several per title.
- A scoped "silently edit any holiday request" permission letting a squad
  member add or cancel a colleague's day directly — never a Chapter Lead's —
  which still emails the chapter lead a recap.

**Calendar data**
- Sprints generated a whole quarter at a time, Monday-to-Friday, in 2-week
  blocks, never overlapping an existing sprint. Manual creation is disabled.
- Bank holidays (excluded from metrics, unbookable) and informational events
  scoped to tribe, cluster or squad.

**Metrics**
- Per-member quarterly worked and absence days against an annual worked-days
  cap, computed in a fixed number of queries regardless of squad size.

**Notifications**
- Emails on submission (approver + watchers), approval, refusal and direct
  edits, all sent only after the transaction commits.

**Operations**
- `app.sh` for setup, dev, test, deploy and production serving.
- gunicorn + WhiteNoise for production; hashed, compressed static assets.
- Security hardening on by default in production; `manage.py check --deploy`
  reports no issues.
- 190 tests.

### Known gaps

- "YTD worked" counts every weekday in the year rather than year-to-date, so
  the cap indicator reads over-cap from January.
- A Chapter Lead sees their own request in their own approval inbox without
  being able to act on it.

[1.0.0]: https://gitlab.com/brieuc/holiday-planning-tool/-/releases/v1.0.0
[1.1.0]: https://gitlab.com/brieuc/holiday-planning-tool/-/releases/v1.1.0
