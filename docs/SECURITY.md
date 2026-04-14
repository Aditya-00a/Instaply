# Security

## Product Security Goals

- private by default
- tenant-isolated
- cloud-hosted
- auditable
- no dependency on a founder machine

## Minimum Security Bar

### Identity

- Supabase Auth
- session validation on every protected request
- role-based access for admin and tester features

### Secrets

- use platform secret managers
- never store provider keys in client code
- rotate keys regularly

### Data

- Postgres for structured state
- object storage for generated files
- signed URLs for temporary access
- encryption at rest through managed providers

### Browser Workers

- isolated sessions per application run
- no persistent shared browser profile
- screenshots/evidence stored per user/job
- blocked outcome on captcha or verification walls

### Auditability

- log every job search
- log every packet generation
- log every browser execution attempt
- log every final outcome

## Things To Avoid

- founder Gmail credentials in production
- shared user accounts
- silent fake-success apply results
- broad filesystem access
- storing raw secrets in source control

