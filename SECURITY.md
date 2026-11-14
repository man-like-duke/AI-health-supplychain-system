# Security policy

## Supported versions

Security fixes are applied to the `main` branch. There are no maintained
release branches at this time.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting:

1. Open the repository's **Security** tab.
2. Select **Report a vulnerability**.
3. Include the affected component, reproduction steps, and the impact you
   believe is possible.

You will receive an acknowledgement through the advisory. Please allow
time for a fix before disclosing the issue publicly.

## Scope

In scope:

- Application code in `src/`, `static/`, and `tests/`.
- Python dependencies listed in `requirements.txt` and
  `requirements-dev.txt`.
- GitHub Actions workflows and repository configuration.

Out of scope:

- `data/facilities.csv` and other synthetic data, which contains no real
  patient or facility records.
- The local `.env` file. It is gitignored and must never be committed.
- Vulnerabilities in third-party services or the Gemini API itself.

## Security pipeline

Every push to `main` and every pull request runs:

| Check | Tool | Workflow |
| --- | --- | --- |
| Secret scanning | Gitleaks | `security.yml` |
| Static analysis | Semgrep | `security.yml` |
| Dependency vulnerabilities | pip-audit | `security.yml` |
| New dependency review | Dependency Review | `security.yml` |
| Software bill of materials | CycloneDX | `security.yml` |
| Deep static analysis | CodeQL | `codeql.yml` |
| Lint, format, tests | ruff, pytest | `ci.yml` |

The security workflows also run on a weekly schedule so newly disclosed
vulnerabilities are detected without a code change. Dependabot opens
grouped weekly updates for Python dependencies and GitHub Actions.

## Local checks

```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files
pip-audit -r requirements.txt -r requirements-dev.txt
```

The Gitleaks pre-commit hook requires a Gitleaks binary on `PATH`.
Download one from the
[Gitleaks releases](https://github.com/gitleaks/gitleaks/releases) or run
the remaining hooks if it is unavailable. To scan the full history
locally:

```bash
gitleaks git --config .gitleaks.toml
```

Semgrep is installed separately because it is not needed to run the
application:

```bash
pip install semgrep==1.185.0
semgrep scan --config p/python --config p/owasp-top-ten \
  --config .semgrep/rules.yml --severity=ERROR --error .
```

## Suppression policy

Suppress a finding only when it is a documented false positive or an
accepted risk:

- **Gitleaks**: prefer a `# gitleaks:allow` comment on the line. If a
  config entry is required, use a rule-scoped `[[rules.allowlists]]`
  entry with `condition = "AND"`; global path-only allowlists suppress
  every finding in that file.
- **Semgrep**: add `# nosemgrep: <rule-id>` with a justification comment.
- **pip-audit**: use `--ignore-vuln <id>` only when no fixed version
  exists, and record the exception in the pull request.

Never suppress a finding by deleting a check or weakening its scope.

## Governance note

This project is a decision-support prototype built on synthetic data. The
pipeline does not deploy the service or act on recommendations, and no
automated step approves a transfer. Any operational use requires review
by an authorized health-program or supply-chain professional.
