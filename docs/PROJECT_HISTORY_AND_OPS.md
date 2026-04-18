# Project History And Ops

This document consolidates historical status/update notes that were previously
scattered in the repository root.

## Why Consolidated

The following files were transient progress notes and are now archived into this
single document to keep the root directory clean:

- `BUG_LIST.md`
- `GITHUB_PUSH_SUMMARY.md`
- `REALTIME_STATUS_UPDATE.md`
- `SCRIPTS_README.md`
- `STRATEGY_LOG_UPDATE.md`
- `STRATEGY_STARTUP_GUIDE.md`
- `WEB_STRATEGY_CONTROL_FIX.md`
- `WEB_UPDATE_SUMMARY.md`

## Historical Summary

- 2026-04: Multiple stability and operability fixes were recorded, including:
  - web status refresh/heartbeat improvements
  - strategy start/stop control consistency in web admin
  - signal log realtime display enhancements
  - logging/rotation and environment/config hardening
- Most listed issues in the old bug list were marked fixed at the time of note.

## Current Recommended Operations

### Start service (Windows)

```powershell
.\start_trading.bat
```

### Stop service (Windows)

```powershell
.\stop_trading.bat
```

### Start strategy engine directly

```powershell
.\venv\Scripts\python run_strategy.py
```

### Start web admin

```powershell
.\venv\Scripts\python -m web_admin.app
```

## Notes

- Keep sensitive credentials only in `.env`.
- Use `.env.example` as the template for shared configuration keys.
- Prefer branch-based development and merge after verification.
