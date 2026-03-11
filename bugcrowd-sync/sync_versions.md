# Sync Version Changelog

This document tracks changes between sync versions. When the sync format changes in a way that requires all submissions to be re-synced, the version is incremented.

## Version 3 (Current)

**Date:** January 16, 2026

**Changes:**
- **Jira integration**: Added Jira task ID (e.g., "BC-62") and clickable link in markdown files when submission is linked to Jira issue
- **Improved author/actor resolution**: 
  - Resolves author names from `relationships.author` and `relationships.actor` fields
  - Resolves from included resources (identity/user objects)
  - Comment and activity headers now show actual usernames instead of "unknown"
- **Activity event metadata**: Activity headers now display activity types (e.g., "Created A Blocker", "Sent A Message") extracted from the `key` field
- **Added "blocked" folder category**: New top-level `blocked/` folder for submissions with blockers (changes file location/path)

**Why re-sync needed:**
- Old files may show "unknown" for author names that now resolve to actual usernames
- Old files may not display activity types (e.g., "Created A Blocker") in activity headers
- Old files won't have Jira task links when submissions are linked to Jira issues
- File locations may change (files with blockers will move to `blocked/` folder)

## Version 2

**Date:** January 2025 (exact date unknown)

**Changes:**
- Added four-folder structure: `new/`, `unresolved/`, `resolved/`, `rejected/`
- Fixed submission ID to be clickable link to BugCrowd tracker
- Fixed attachment image link rewriting for `/engagements/codeorg/security-inbox/submissions/...` URLs
- Added filename-based fallback matching for attachment images
- Moved attachments section outside of reproduction steps (always shows when attachments exist)
- Added sync version tracking to state file

**Why re-sync needed:**
- Folder structure changed (from `resolved/` and `unresolved/` to four categories)
- Image link rewriting improved to handle more URL formats
- Attachments section positioning changed

## Version 1 (Initial)

**Date:** December 2024 (exact date unknown)

**Changes:**
- Initial implementation
- Two-folder structure: `resolved/` and `unresolved/`
- Basic attachment downloading
- Image link rewriting for embed URLs
- Comments and activity formatting

