# docs/ — Project Documentation

This directory contains the canonical documentation for the ckdigitalyt video engine. It is organized to support software engineering best practices — traceability, reproducibility, and asynchronous collaboration.

## Directory Structure

| Directory       | Purpose |
|-----------------|---------|
| `docs/` (root)  | Detailed technical documentation for each subsystem (planner, cinematics, renderer, providers, asset pipeline, etc.). |
| `investigations/` | Bug reports, root-cause analyses, and performance investigations. Each report follows the template in `REPORT_TEMPLATE.md`. |
| `architecture/` | System architecture documents, ADRs (Architecture Decision Records), and high-level design diagrams. |
| `decisions/` | Technical decisions, trade-off analyses, and rationale for implementation choices. |
| `implementation/` | Implementation plans, migration guides, and feature-scoping documents. |
| `handovers/` | Project handover reports intended for new contributors or AI agents onboarding to the codebase. |

## Conventions

- All Markdown files use UTF-8 encoding and Unix line endings.
- Investigations MUST use `docs/investigations/REPORT_TEMPLATE.md` and be saved under `docs/investigations/`.
- All documents should be committed and pushed to the `jade` branch after creation or significant update.
- Do not paste large reports into chat/Discord — reference the file path instead.
