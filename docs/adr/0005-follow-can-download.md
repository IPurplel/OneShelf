# ADR 0005 — A Follow may download its new releases, when the person asks

Status: accepted (2026-11-10).

Until now a Follow only reported new releases ("Follow never downloads automatically", REFERENCE §16). The
owner asked for releases to be ready to read offline as they appear, and chose how: a switch per Work, on its
page, rather than one setting for every Follow.

**Off unless turned on.** `follows.auto_download` defaults to 0, so every existing Follow keeps notifying only.
The switch is offered on a followed source track that can deliver files; a read-only source has nothing to keep.

**Only what is new.** When a check reports new releases (the same detection as before: trusted catalog against
baseline, never numbers), the Follow runner queues exactly those units, in catalogue order, as one batch
labelled with the Work. Turning the switch on never downloads what was already in the catalogue.

**Downloading never decides detection.** A batch that cannot be queued (no storage location yet, a source that
stopped delivering files) is logged; the release is still reported, and the next release is tried again.
Downloads use the normal engine, at its own priorities, so a Follow's batch never jumps ahead of the person's.

**Kept through undo.** Undoing an unfollow restores the switch with the Follow. A Library Backup carries it
with the `follows` table; an older backup restores with the switch off.
