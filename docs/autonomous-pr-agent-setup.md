# Autonomous PR Agent Setup

This repository includes GitHub Actions automation for branch-to-PR creation,
quality gates, AI pull-request review, and squash auto-merge when the AI review
returns an explicit approval.

## Installed Files

- `.github/workflows/auto-create-pr.yml`
- `.github/workflows/autonomous-pr-agent.yml`
- `config/pr-review-rules.json`
- `scripts/review_pull_request.py`

The root `AGENTS.md` remains the source of coding-agent instructions for this
project. The PR-agent policy lives in `config/pr-review-rules.json`.

## Required GitHub Configuration

Add this repository secret:

- `NVIDIA_API_KEY`

Optional repository variables:

- `NVIDIA_BASE_URL`, defaulting to `https://integrate.api.nvidia.com/v1`
- `NVIDIA_MODEL`, defaulting to `nvidia/llama-3.3-nemotron-super-49b-v1.5`

Enable these repository settings:

- Allow squash merging
- Allow auto-merge
- Allow GitHub Actions to create and approve pull requests
- Read and write workflow permissions

Protect `main` with:

- Pull requests required before merge
- Required status checks
- Branches up to date before merge
- No force pushes
- No branch deletion
- No direct pushes

After the workflows run once, select these required checks:

- `Quality Gate`
- `AI Review`

## Verification Commands

The quality gate runs:

```bash
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m alembic upgrade head
python -m alembic check
```

## Safety Notes

The reviewer fails closed when the API key is missing, the NVIDIA API is
unavailable, the AI review blocks, or quality checks fail. Every PR gets a
review summary comment before the AI decision is enforced.

High-risk and critical changes are still labeled in the review comment, but
they can merge automatically when the NVIDIA reviewer explicitly approves them.
This makes the repository fully autonomous, so keep branch protection and
required status checks enabled.

The reviewer uses NVIDIA NIM's OpenAI-compatible chat completions endpoint:

```text
POST https://integrate.api.nvidia.com/v1/chat/completions
```
