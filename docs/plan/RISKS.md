# Risks

What could still go wrong, what has been done about it, and what has not. Kept short and honest: a
risk that is fully handled is closed, not left open to look thorough.

Updated: 2026-09-21

## Open

| # | Risk | Likelihood / impact | What reduces it | What remains |
|---|---|---|---|---|
| R-01 | **The container gate has never run.** No container runtime exists inside this development environment, so the image has never been built, started, restarted or recreated anywhere. | Medium / high — it is the difference between "should install" and "does install" | The Dockerfile, Compose file and scripts are written against the real readiness and health endpoints; script behaviour is covered by 23 tests against stub runtimes; the frontend build and same-origin serving were verified outside a container, including in a browser | Only a real host can close it. M2, M2.1 and M56 stay open until Fedora + Podman evidence exists. Exact commands: `docs/c9/verification.md` §3a |
| R-02 | **A source changes its markup and a capability quietly degrades.** Seven of the eight sources are scraped HTML or a site's own XHR. | High over time / medium — a source stops working, the rest are unaffected | Every adapter ships fixtures captured from the real responses and is exercised offline on every test run; the live suite opens real artefacts; extraction failures are reported as incomplete with evidence rather than as short results; the generator's Repair flow diffs selectors against the live site | Expected maintenance, not a defect. The live suite is the early warning and is opt-in by design |
| R-03 | **A published repository invites use, and no licence has been chosen.** | Certain / low, but legally real | The README states plainly that no licence is granted yet | The owner's decision. Until a `LICENSE` file exists, others may read the code but have no right to use it |
| R-04 | **Rootless Podman bind-mount ownership varies between distributions.** | Low / medium — install fails on an unusual setup | `install.sh` probes writability and only corrects ownership when needed, through the runtime, never with sudo (ADR 0002); the README's troubleshooting section names the symptom | Unknown until the gate runs on a real Fedora host |
| R-05 | **gutendex.com times out intermittently** (E-03). | Medium / low | Diagnosed as external twice, with evidence; OneShelf reports it honestly as incomplete with a transport issue; the live suite skips only on that exact signature | Nothing to fix in OneShelf |

## Closed

| # | Risk | How it was closed |
|---|---|---|
| R-C1 | The image would have shipped without an interface | Found while writing the installer; the SPA is now built into the image and served from the API's own origin, with the boundary tests to prove it did not weaken anything (ADR 0001) |
| R-C2 | `.env` or library data committed to a public repository | `.gitignore` covers `/.env`, `/deploy/volumes/`, `*.osbackup` and local databases; a content scan of all 533 tracked files found nothing secret-shaped; the only credential in the tree is the Test Source's deliberate fake, which a test asserts never reaches disk |
| R-C3 | An uninstall that destroys a library by accident | Data deletion is never the default, is a separate named flag, lists the exact directories, requires typing a sentence in full, and refuses obviously wrong targets. Two tests hold it |
| R-C4 | 3asq unreachable, leaving the §41 suite incomplete | It was a moved domain, not an unreachable host; the adapter ships against 3asq.online and is verified live |
