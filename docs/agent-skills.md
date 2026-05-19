# Agent Skills

OmniClaw core skills are buyer-oriented.

Use these flows when an agent needs to inspect or pay a URL through the policy engine:

```bash
omniclaw-cli can-pay --recipient https://paid.example.com/compute
omniclaw-cli inspect-x402 --recipient https://paid.example.com/compute
omniclaw-cli pay --recipient https://paid.example.com/compute --idempotency-key job-123
```
