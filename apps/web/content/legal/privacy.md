# Privacy Policy

**Effective Date:** 14 April 2026
**Last Updated:** 15 April 2026

## 1. Controller

The Data Fiduciary / Controller of personal data processed by Instaply is:

**Ravendise** — a proprietorship registered in India.

Privacy contact: **hello@asion.ai**

This policy applies to all Instaply surfaces: the web app at **instaply.asion.ai**, the Claude Desktop MCP, and the ChatGPT Connector.

## 2. Data we collect

### 2.1 You provide directly
- **Account data:** email, full name, password (hashed), phone (optional)
- **Professional profile:** resume file, work history, education, skills, LinkedIn/GitHub URLs
- **Work authorization:** citizenship/visa status, sponsorship needs, location
- **Demographic data (optional, for EEO compliance):** gender, race/ethnicity, veteran status, disability status — provided only if you choose to fill them
- **Preferences:** target roles, locations, salary expectations, excluded companies
- **Payment data:** handled by our payment processor (Razorpay). We never store your full card number.

### 2.2 Automatically
- Log data (IP address, user agent, timestamps)
- Application submission logs (which fields were filled, confirmation-email matches)
- Service usage metrics (credits consumed, which surfaces you use)

### 2.3 From third parties
- Confirmation-email metadata when you connect your Gmail account (read-only, restricted to messages matching known ATS sender patterns)
- Public job postings from Applicant Tracking Systems (Greenhouse, Lever, SmartRecruiters, Workday, etc.) — these contain no personal data about you

## 3. Why we process it (legal basis)

Under the Indian **Digital Personal Data Protection Act, 2023** ("DPDP Act") and, where applicable, the EU **GDPR**:

| Purpose | Legal basis |
|---|---|
| Creating and maintaining your account | Contract performance |
| Submitting applications on your behalf | Contract performance |
| Credit accounting and billing | Contract performance + legal obligation |
| Customer support | Contract performance |
| Service improvement and debugging | Legitimate interest |
| Fraud prevention | Legitimate interest + legal obligation |
| Marketing communications | Consent (opt-in, revocable) |

**Demographic data** is processed solely to auto-fill employer EEO forms when you direct us to, and only with your explicit consent during profile setup.

## 4. Third parties who process data on our behalf (sub-processors)

| Sub-processor | Purpose | Location |
|---|---|---|
| Supabase Inc. | Hosted Postgres, auth, file storage | USA (with India region option) |
| Railway / Fly.io | API + worker hosting | USA / EU |
| NVIDIA Corporation (NIM) | AI inference for ranking + cover letters | USA |
| Anthropic / OpenAI (optional fallback) | AI inference | USA |
| Razorpay Software Pvt. Ltd. | Payment processing | India |
| Google LLC (Gmail API) | Confirmation-email verification (if you connect) | USA |
| Vercel Inc. | Frontend hosting | USA |

We do not sell your personal data. We do not share your personal data with employers beyond the information you explicitly submit in an application.

## 5. Cross-border transfers

Because our sub-processors are primarily located outside India, your data may be transferred internationally. Where required, we rely on:

- **Standard Contractual Clauses** (for EU data transfers out of the EEA)
- **DPDP Act § 16** permissions for transfers from India
- Security measures (encryption in transit and at rest, access controls, audit logging)

## 6. Retention

- **Account data:** retained while your account is active, and for 90 days after deletion to handle disputes and legal obligations
- **Application logs:** retained for 12 months for service quality and audit
- **Payment records:** retained for 7 years per Indian tax law (Income Tax Act, GST Act)
- **Deleted data:** removed from active systems within 30 days; backups purged within 90 days

## 7. Your rights

Under the DPDP Act and GDPR (where applicable), you have the right to:

- **Access** the personal data we hold about you
- **Correct** inaccurate data
- **Erase** your data (subject to retention obligations)
- **Port** your data to another service
- **Withdraw consent** for any consent-based processing
- **Object** to processing based on legitimate interest
- **Lodge a complaint** with the Data Protection Board of India (DPB) or your local supervisory authority

To exercise any right: email **hello@asion.ai**. We respond within 30 days.

### 7.1 California residents (CCPA / CPRA)

If you are a California resident, in addition to the rights above you have the right to:

- **Know** what categories of personal information we collect, the sources, the purposes of collection, and the categories of third parties with whom we share it (all listed in Sections 2-4 of this policy)
- **Access** the specific pieces of personal information we hold about you
- **Delete** your personal information, subject to exceptions permitted by law (see Section 6 on retention)
- **Correct** inaccurate personal information
- **Opt out of "sale" or "sharing"** of your personal information. **We do not sell or share personal information** as those terms are defined under the CCPA/CPRA. We do not use personal information for cross-context behavioral advertising.
- **Limit use of sensitive personal information** — we use sensitive categories (e.g., immigration / work-authorization status, demographic data) only to provide the Service you requested and never for inferring characteristics about you
- **Non-discrimination** — we will not deny service, charge a different price, or provide a different level of service because you exercised a CCPA right
- **Authorized agent** — you may designate an agent to make a request on your behalf; we will require reasonable verification

To exercise any California right: email **hello@asion.ai** with the subject line "CCPA request". We respond within 45 days (extendable to 90 days with notice). We may need to verify your identity by matching information you provide against information in our records.

We retain the categories of personal information described in Section 2 for the periods described in Section 6.

## 8. Security

We apply industry-standard safeguards:

- TLS 1.3 encryption in transit
- Encryption at rest for all databases (AES-256 via Supabase)
- Row-level security enforcing per-user data isolation
- Principle of least privilege for staff access
- Append-only credit ledger (tamper-evident)
- Regular security reviews of sub-processors

No system is perfectly secure. If we become aware of a breach affecting your data, we will notify you and the DPB within 72 hours as required by law.

## 9. Children

The Service is not directed to individuals under 18. We do not knowingly process data of children. If you believe a minor has registered, contact **hello@asion.ai** and we will delete the account.

## 10. Cookies and similar technologies

`instaply.asion.ai` uses essential cookies only (session, CSRF protection). We do not use advertising cookies or third-party trackers on authenticated pages. Marketing pages may use a single first-party analytics cookie (configurable in preferences).

## 11. Changes to this policy

Material changes will be notified by email and via in-app banner at least 14 days before they take effect.

## 12. Contact

**Privacy / DPDP / GDPR requests:** hello@asion.ai
**Grievance Officer** (per DPDP Act § 8(9)): contact via **hello@asion.ai**

Response time: within 30 days of receipt.
