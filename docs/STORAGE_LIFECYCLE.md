# Temporary review preview lifecycle

Make It Pop is a feedback and project workspace, not a file-storage product. Designers keep editable source files and final exports on their local disk, Google Drive, Dropbox, or the delivery system they already use.

## What Make It Pop keeps

The lightweight collaboration record remains available:

- projects and design item metadata;
- comments and threaded replies;
- revision tasks and their completed state;
- version numbers and notes;
- approval or change-request decisions;
- who participated and when.

## What Make It Pop removes

The image or PDF uploaded for browser review is a temporary preview. Approval starts a 10-day grace period. After the grace period, the cleanup job deletes every Make It Pop-managed preview for that design and replaces it with an “expired preview” placeholder.

Reopening an approval before cleanup cancels the pending deletion. Uploading a new version also returns the design to review. External links are never deleted by Make It Pop.

The 10-day grace period gives the team enough time to finish publishing or catch an accidental approval without turning Make It Pop into a long-term asset library.

## Cleanup operation

Run this idempotent command at least daily in production:

```powershell
python -m assetflow.jobs.cleanup_previews
```

It only deletes files inside the configured Make It Pop upload directory, records `preview_deleted_at`, and leaves all collaboration metadata untouched. Development also runs cleanup once at application startup.

For a production deployment, the same lifecycle can target a small private object bucket instead of local disk. That is infrastructure for temporary previews, not a customer-facing storage tier or quota system.
