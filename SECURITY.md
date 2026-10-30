# Security and privacy

LoraSuite is a local application with filesystem access. Its Python API is intended for a single-user machine and binds to loopback by default. Do not expose it through a reverse proxy, public interface, port forward, or shared hosted service. Requests from unrelated browser origins are rejected; this is not multi-user authentication or a sandbox against other programs running as you.

The Chrome companion has access to supported model pages and loopback services. Its paired project bridge uses a revocable token and a restricted API. LoRA Manager remains a separate service with its own access controls. The companion cannot authorize arbitrary engine filesystem operations.

Project files, source manifests, previews, provider outputs and logs can contain personal data. Keep the vault, `.env` files, browser profiles, credentials and support bundles out of issues and commits. Desktop secrets use the system credential store; web secrets are session-only. Review external service inputs and dataset permissions before running acquisition, captioning, training or generation.

## Reporting a vulnerability

Do not put credentials, private media, exploit details involving personal data, or unredacted logs in a public issue. Use GitHub's **Security → Report a vulnerability** when available. If private reporting is unavailable, open an issue asking for a private contact channel without sensitive details.

This preview has no security-support SLA. Report the exact tag/commit, platform, reproduction steps and impact. Dependency scans and local tests do not constitute a comprehensive security audit.
