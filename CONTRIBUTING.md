# Contributing to FilesMind

Thank you for contributing to FilesMind.

## Development Setup

1. Clone the repository.
2. Install Python dependencies from the project root:

```bash
python -m pip install -U uv
uv sync
```

3. Start backend:

```bash
cd backend
uv run uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

4. Start frontend in a new terminal:

```bash
cd frontend
npm install
npm run dev
```

## Pull Request Guidelines

1. Keep PRs focused and small when possible.
2. Describe what changed and why.
3. Include reproduction steps for bug fixes.
4. Update docs when behavior or setup changes.

## Contribution License Terms

By submitting a contribution to this repository, you agree that:

1. Your contribution is licensed under `AGPL-3.0-or-later` as part of this project.
2. The project maintainer may also use and distribute your contribution under commercial license terms as part of FilesMind's dual-licensing model.
3. You confirm you have the legal right to submit the contribution under these terms.

## Local Checks

Run full project checks before opening a PR:

```bash
./scripts/test_all.sh
```

## Reporting Issues

When opening an issue, include:

1. Environment (OS, Python, Node versions)
2. Steps to reproduce
3. Actual behavior and expected behavior
4. Relevant logs or screenshots
