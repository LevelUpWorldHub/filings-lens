# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

- Use GitHub's private reporting: **Security → Advisories → Report a vulnerability** on this repository (if enabled), or
- contact the maintainer (@LevelUpWorldHub) privately through GitHub.

Include the affected commit or version, steps to reproduce, and the impact. We aim to acknowledge reports within 3 business days.

## Supported versions

Only the latest commit on the default branch is supported.

## Secrets

Never commit credentials. Keep local values in a git-ignored `.env` file and use GitHub Actions secrets for CI.
