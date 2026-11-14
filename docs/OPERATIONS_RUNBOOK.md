# Operations Runbook

| Task | Command / action |
|---|---|
| Start server | `python main.py serve` (UI + API) |
| Health check | `python main.py check` (exit code 1 on any FAIL). Liveness for monitoring: `GET /api/health` |
| Apply migrations / resync roles after editing `security.yaml` | `python main.py init-db` |
| Add user | `python main.py create-user --username u --role HOD --department SALES` |
| Locked-out user | Wait out `lockout_minutes`. An admin unlock UI is planned. |
| Logs | `logs/app.log` (JSON lines, rotated at 10 MB × 10) |
| Login audit | `audit.user_activity_log` |

Backup and restore procedures are defined with IT in Phase 14. A backup is not called valid until a restore has been tested.
