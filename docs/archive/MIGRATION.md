# Repository move to `SWORT-Aerospace/sem-motor-controller` (v0.3 record; completed)

**Status: completed.** The project now lives at the root of `SWORT-Aerospace/sem-motor-controller`. This page is kept as the record of where the earlier history is and how the move was verified.

## Before the move (v0.1 to v0.3)
* Folder `sem-motor-controller/` in `andrefp-co/swort`, branch `claude/nice-bell-98hxr2` (the development branch name, kept here as provenance). The site repository's `main` (the website deployment) was not modified; no pull request was opened there.
* Creating a repository in the organisation was refused to the development tooling (`POST /orgs/SWORT-Aerospace/repos` returned `403 Resource not accessible by integration` on 2026-10-14 and 2026-10-15): it needs organisation-administration permission. An organisation owner created the empty repository.

## How the history was moved
```sh
git clone https://github.com/andrefp-co/swort.git && cd swort
git checkout claude/nice-bell-98hxr2
git subtree split --prefix sem-motor-controller -b semmc-export   # project history only, deterministic
git push https://github.com/SWORT-Aerospace/sem-motor-controller.git semmc-export:main
```
Verification (re-run 2026-10-16): `git rev-parse origin/main^{tree}` of the new repository at `19a327c` and `git rev-parse claude/nice-bell-98hxr2:sem-motor-controller` of the old one at `8977499` are both `54e1ece80ef136eb57e9140a4a83eb7f34585ea1`. The history starts with the first sem-motor-controller commit. CI runs from the repository root.

## Open decisions for the repository owner
* Whether to remove the folder from `andrefp-co/swort` (a separate change in that repository).
* Branch protection on `main` (pull requests and CI required) and collaborator invitations (telematics engineer, vehicle team).
