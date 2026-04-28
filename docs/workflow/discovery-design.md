# Discovery Design

Discovery creates lead candidates. It does not enrich them.

The first rebuild priority is the worker. Discovery should be rebuilt only after the worker contract is stable.

## Discovery Responsibility

Discovery should produce:

- `company_name`
- optional source metadata
- optional discovery category
- optional discovery area

Discovery should not produce:

- final homepage URL
- parent company
- enrichment confidence
- website scrape

## Handoff Contract

The worker must be able to run with only:

```json
{
  "company_name": "Example Company"
}
```

Additional discovery fields are allowed only for audit context.

## Success Criteria

Discovery is successful when:

- it creates relevant Singapore target companies for Rayn Secure outbound.
- it avoids obvious non-company entities.
- it does not force downstream homepage choices.
- it keeps enough source context to audit where the lead came from.
