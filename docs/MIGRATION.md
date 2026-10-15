# Moving the project to `SWORT-Aerospace/sem-motor-controller`

## Where the project is now
* Folder `sem-motor-controller/` in `andrefp-co/swort`, branch `claude/nice-bell-98hxr2`.
* The site repository's `main` (the website deployment) is untouched.
* No pull request, no merge.

## Why Claude could not create the repository
* `POST /orgs/SWORT-Aerospace/repos` returned `403 Resource not accessible by integration`, on 2026-10-14 and once more on 2026-10-15, after which it was not retried.
* The Claude GitHub App can read and push to existing SWORT-Aerospace repositories. Its installation cannot create repositories in the organisation, which needs organisation-administration permission.
* An organisation owner has to create the empty repository. That takes about a minute.

## Steps (organisation owner)
1. **Create the repository** at github.com/organizations/SWORT-Aerospace/repositories/new:
   * name `sem-motor-controller`, private;
   * **no** README, licence or .gitignore, so the first push lands on an empty repository.
2. **Give the Claude GitHub App access**: organisation Settings → GitHub Apps → Claude → Repository access. Choose "All repositories", or add `sem-motor-controller`.
3. **Push the history.** Either:
   * **(a) Ask Claude.** In this session or a new one, say "push the project to SWORT-Aerospace/sem-motor-controller". Claude attaches the repository and runs the commands in (b).
   * **(b) By hand**, on any machine with git:
     ```sh
     git clone https://github.com/andrefp-co/swort.git && cd swort
     git checkout claude/nice-bell-98hxr2
     git subtree split --prefix sem-motor-controller -b semmc-export   # project history only, deterministic
     git push https://github.com/SWORT-Aerospace/sem-motor-controller.git semmc-export:main
     ```
4. **Verify.** In the new clone, `git rev-parse HEAD^{tree}` must equal `git rev-parse claude/nice-bell-98hxr2:sem-motor-controller` in the old one. The history starts with the first sem-motor-controller commit.
5. **CI activates by itself.** `.github/workflows/ci.yml` is inert in a subdirectory and runs once it is at a repository root.

## After the move (recommended for collaboration)
* Invite the telematics engineer and the vehicle team. Protect `main` (pull requests and CI required).
* Give each item of `docs/PHYSICAL_TEAM_QUESTIONNAIRE.md` its own issue, so answers carry an author and a date.
* Share `protocol/generated/semmc_base0x300.dbc` with the telematics engineer, or regenerate it for the allocated block with `tools/gen_dbc.py --base …`.
* Keep the folder in `andrefp-co/swort` until the new repository is verified. Removing it from the site repository is the owner's decision and a separate change; Claude will not do it unasked.
