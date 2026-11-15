# Use of AI in this project

**DRAFT for the team to confirm before submission.** The section "What the AI tool did" was written by the
tool itself, from its own working sessions. Every line marked `TEAM TO CONFIRM:` is for a human team member
to fill in or correct. Nothing on this page is final until the team has checked it.

## What NASA Space Apps asks

- AI tools may be used, but they should not be used to come up with the idea for how to solve the challenge.
- AI-generated code must be acknowledged in descriptive text and metadata.

TEAM TO CONFIRM: that these two points match the current participant rules, read at the source.

## What the AI tool did

The tool is Claude Code (Anthropic). It was used to:

- research the challenge and the data;
- draft the build plan (`docs/plan.md`), as a proposal for the team to adopt, change or reject;
- write and review most of the code and tests on the `dev` branch, working from measurements made on real
  SPHEREx data on 14 November 2026 (the scripts are in `science/prototypes/`);
- draft the documentation, including this page.

## What is not AI-generated

- No image, video or audio in the project is AI-generated.
- Every pixel shown comes from NASA archives. The sources are listed in `docs/DATA_SOURCES.md`.
- The repository rule is "real data only": invented numbers appear only as small arrays in unit tests of
  pure maths, named `synthetic_*`, and are never shipped.

## What the team did

TEAM TO CONFIRM: how the idea for the solution came about, and who chose it.

TEAM TO CONFIRM: which concept choices of the drafted plan the team adopted, changed or rejected.

TEAM TO CONFIRM: the three choices marked DECIDE in `CLAUDE.md`, section 0 (front-end stack, hosting and
account holder, project name): what was decided, and by whom in the team (roles, not names).

TEAM TO CONFIRM: which code, tests and documents team members reviewed, and how (read, ran, changed).

TEAM TO CONFIRM: which results team members verified themselves, and against what (for example the measured
motion of Barnard's Star and of WISE 0855).

TEAM TO CONFIRM: who wrote and delivered the pitch, the slides and the demo, and whether any AI tool was used
for them.

TEAM TO CONFIRM: any other AI tool a team member used, and for what.

## Where the acknowledgement appears

In the repository today:

- this page, and the pointer to it in `README.md`;
- the description fields of `api/pyproject.toml` and `web/package.json` ("Built with AI assistance").

TEAM TO CONFIRM: the wording of the acknowledgement on the NASA Space Apps project page.

TEAM TO CONFIRM: whether to add an "About" text in the app and an HTML meta tag, as the plan proposes. Neither
exists yet.

TEAM TO CONFIRM: commit messages carry no AI attribution, by a standing rule of this repository. Check that
this page, the README and the metadata above are enough to meet the rule on acknowledging AI-generated code.
