# 0006 - Autonomous Pull Request Agent

## Status

Accepted

## Context

The project needs repeatable quality gates and lightweight pull-request review
automation while preserving manual control for risky changes. The repository is
still local-first and cost-sensitive, so automation must not add runtime
dependencies to the application or require paid services for local development.

## Decision

Add GitHub Actions workflows that create pull requests from non-protected
branches, run the project verification commands, request an NVIDIA NIM AI
review, and enable squash auto-merge only for low or medium risk changes.

The review policy is stored in `config/pr-review-rules.json`, and the review
script is stored in `scripts/review_pull_request.py`. The project root
`AGENTS.md` remains unchanged as the coding-agent instruction source.

## Alternatives Considered

- Manual-only pull requests: simpler, but less consistent and easier to skip
  verification.
- Fully autonomous direct pushes to `main`: rejected because it bypasses branch
  protection and human control for risky changes.
- Adding the downloaded package's root `AGENTS.md`: rejected because it would
  conflict with this repository's permanent coding-agent instructions.

## Consequences

- GitHub must be configured with `NVIDIA_API_KEY`, workflow write permissions,
  branch protection, and required checks before automation can operate.
- AI review failures fail closed and prevent autonomous merging.
- The default NVIDIA endpoint is `https://integrate.api.nvidia.com/v1`, and the
  model is configurable through `NVIDIA_MODEL`.
- Changes to workflows, migrations, reviewer code, and reviewer policy are
  classified as high or critical risk and require manual attention.
