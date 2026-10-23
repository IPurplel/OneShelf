# Frozen official adapters (test fixture)

A copy of `backend/plugins/official/` as it was before the 2026-10-20 snapshot refresh (Core audit WP-14),
including the MangaDex 1.0.2 local hotfix. Tests of mechanisms — tier rules, version immutability, the
Registry build, bundled-update paths, permission review — derive their inputs from these files by editing
known text (`version: 1.0.0`, a fixture name). Keeping them here means a release snapshot refresh no longer
changes what those tests test. Tests of the *shipped* snapshot itself (packaged tests, image contents,
first-run install) still read `backend/plugins/official/`. Never sync this directory.
