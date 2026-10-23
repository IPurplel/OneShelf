# Merge integration contract

The owner requested committing, pushing, and merging all OneShelf changes on 2026-10-23.
Review of the combined UI-003 frontend/backend changes found that a download job's
availability could refer to PDF while the Reader implicitly chose EPUB.

The additive contract is `available_format: string | null` on batch-detail jobs.
It identifies the same present local copy used to calculate `available`; absent
copies return null. Downloads includes it in its Reader link and ReadRoute honors
supported formats in the unit context. Existing clients retain `available`.
This narrow cross-boundary integration correction leaves storage and Reader file
selection logic unchanged. Backend ownership remains with Claude Code.

Batch details also use the existing offset/limit/jobs_total contract to page beyond
500 jobs. Search conflict resolution retains both Grid/List and reduced-motion-aware
entry animations. Agent instructions from both branches are retained.

Production deployment and Chrome QA remain pending the owner's manual update.
