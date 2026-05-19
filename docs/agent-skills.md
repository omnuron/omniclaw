# Agent Skills

OmniClaw core skills are buyer-oriented.

Use these flows when an agent needs to inspect or pay a URL through the policy engine:

```bash
omniclaw-cli can-pay --recipient https://seller.example.com/compute
omniclaw-cli inspect-x402 --recipient https://seller.example.com/compute
omniclaw-cli pay --recipient https://seller.example.com/compute --idempotency-key job-123
```

Seller-side paid endpoint hosting and facilitator operations are handled by:

```text
services/hosted-facilitator/
```
