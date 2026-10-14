# ADR-0001 — Project placement

**Context.** The request asked for the project "inside of SWORT Aerospace". This session can push only to `andrefp-co/swort` (the SWORT website deploy repository), on branch `claude/nice-bell-98hxr2`. Creating a new remote repository in the SWORT-Aerospace organization was not explicitly authorized, and the CSIA research repository must not be reorganized.

**Decision.** Build a self-contained project at `sem-motor-controller/` inside `andrefp-co/swort` on the feature branch. Nothing outside that directory is modified. CSIA is consumed as a **pinned external dependency** (`third_party/csia-trust-layer.lock`, fetched into the git-ignored `.deps/`), never vendored.

**Consequences.**
* `sem-motor-controller/.github/workflows/ci.yml` is inert until the directory becomes a repository root, because GitHub reads workflows only from the root.
* The host repository is a static-site deploy target. If its hosting builds previews from feature branches, files under this directory could be served on a preview URL. Nothing here is secret, but **do not merge this branch to `main`** (that would publish it on the production site). Move it to a dedicated private repository (e.g. `SWORT-Aerospace/sem-motor-controller`) with `git subtree split --prefix sem-motor-controller`.
* Reopen when the owner confirms the destination repository.
