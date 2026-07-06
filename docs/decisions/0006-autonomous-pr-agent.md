# 0006 - Autonomous Pull Request Agent

## Status

Accepted

## Context

The project needs repeatable quality gates and lightweight pull-request review
automation while avoiding manual review for routine development. The repository
is still local-first and cost-sensitive, so automation must not add runtime
dependencies to the application or require paid services for local development.

## Decision

Add a GitHub Actions workflow that runs the project verification commands on
manually opened pull requests, requests an NVIDIA NIM AI review, runs a
Ponytail-style senior simplification pass, posts a review summary comment, and
enables squash auto-merge when the AI review returns an explicit approval.

The review policy is stored in `config/pr-review-rules.json`, and the review
script is stored in `scripts/review_pull_request.py`. The simplification pass is
based on `DietrichGebert/ponytail`'s `ponytail-review` guidance, but it is
implemented as config-driven reviewer instructions instead of executing
third-party code during CI. The project root `AGENTS.md` remains unchanged as
the coding-agent instruction source.

## Alternatives Considered

- Automatic branch-to-PR creation: convenient, but rejected because some
  repositories disallow GitHub Actions from creating pull requests.
- Fully autonomous direct pushes to `main`: rejected because it bypasses branch
  protection and human control for risky changes.
- Blocking high and critical PRs from auto-merge: safer, but rejected because
  this repository now prioritizes fully autonomous PR review and merge gates.
- Checking out and executing the Ponytail repository in CI: rejected because the
  useful PR-review value is its over-engineering guidance, while executing
  unpinned third-party code would add supply-chain and reliability risk.
- Adding the downloaded package's root `AGENTS.md`: rejected because it would
  conflict with this repository's permanent coding-agent instructions.

## Consequences

- GitHub must be configured with `NVIDIA_API_KEY`, workflow write permissions,
  branch protection, and required checks before automation can operate.
- Contributors must open pull requests manually from feature branches.
- AI review and simplification-review failures fail closed and prevent
  autonomous merging.
- The default NVIDIA endpoint is `https://integrate.api.nvidia.com/v1`, and the
  model is configurable through `NVIDIA_MODEL`.
- The simplification pass is advisory for merge decisions: it reports senior
  simplification opportunities but does not override correctness, security,
  migration, or quality-gate results.
- Changes to workflows, migrations, reviewer code, and reviewer policy are
  classified as high or critical risk in the review comment, but an explicit AI
  approval can still pass and enable auto-merge.
