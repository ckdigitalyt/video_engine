# docs/investigations/ — Investigation Reports

This directory stores structured investigation reports for bugs, performance regressions, failures, and unexpected behavior.

## Report Format

Every investigation report MUST follow the schema defined in `docs/investigations/REPORT_TEMPLATE.md`. This ensures consistency and makes reports machine-readable and reviewable.

## Naming Convention

Use lowercase with hyphens:

```
docs/investigations/YYYY-MM-DD-brief-description.md
```

If an investigation spans multiple days, use the start date.

## Lifecycle

1. **Investigate** — gather evidence, reproduce, log findings.
2. **Report** — write a Markdown report using the template.
3. **Commit** — commit the report to the `jade` branch.
4. **Push** — push to origin.
5. **Reference** — link the report file from the relevant issue, PR, or chat summary.
