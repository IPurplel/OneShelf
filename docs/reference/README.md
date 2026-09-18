# Approved visual reference

Put the approved OneShelf visual reference here, as a file **written fresh into this folder** (Save As,
Export, or a copy made by an application), not moved from a download directory:

```
docs/reference/oneshelf-library-home.png     (or .webp / .jpg)
```

Why "written fresh": a file that arrives by download or move can carry a security label from where it came
from. This project's tooling then cannot open it — the failure looks like `Permission denied` on `stat`,
which no `chmod` will fix. A file created directly in this folder inherits the folder's context and is
readable normally.

The reference is authoritative for the visual direction (Master §32): the overall composition, the
material and colour language, and the shelf motif. Master §32's written rules still win where the two
disagree — in particular there is no profile or avatar in the header, and the adaptive content rules
apply.

Until a reference is present, C2's "responsive Arabic/English visual checks against the reference" gate is
recorded as blocked (EB-2) rather than passed.
