# Holiday Planning Tool

Internal Django app for planning and approving time off across a
Tribe → Cluster → Squad organisation.

- **Squad calendar** — who's away, sprints, bank holidays and events; click days to request time off (full or half).
- **Per-day approval** — a Chapter Lead approves or refuses each day individually, with a required justification on refusal.
- **Metrics** — quarterly worked and absence days per member against an annual worked-days cap.
- **Admin** — Scrum Masters manage people, org structure, titles, sprints, bank holidays and events.

## Quick start

```bash
./app.sh setup       # venv + dependencies + .env (with a generated SECRET_KEY) + migrations
./app.sh bootstrap   # create the tribe and the break-glass admin account
./app.sh dev         # http://127.0.0.1:8000
```

`./app.sh help` lists every command.

## Roles and permissions

There is no "Scrum Master" role. Two things are configured independently:

| Concept | Where it's set | What it grants |
|---|---|---|
| **Admin access** | a Title with *grants admin access* | reaches `/admin/`, manages the tribe |
| **Approver** | a User with role *Chapter Lead* + a Title | approves holiday requests for everyone holding that title |
| **Backup approver** | *Backup chapter lead assignments* | stands in for a title's Chapter Lead; any user is eligible |
| **Silent edit** | *Can silently edit any holiday request* on a User | set a squad member's day directly from the calendar, bypassing approval (never for a Chapter Lead); emails the chapter lead a recap |

Assigning role *Chapter Lead* + a title is the whole mechanism — it also
re-routes any already-pending requests for that title.

## Sprints

Sprints are only ever created a whole quarter at a time, via **Generate
sprints for a quarter** in the admin (manual "add" is disabled). Ranges must
run Monday→Friday, divide into whole 2-week sprints (max 8 per quarter), and
must not overlap sprints that already exist.

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

190 tests covering the request/approval workflow, routing and backup
approvers, sprint generation and overlap rules, metrics, and RBAC across
both the app and the admin.
