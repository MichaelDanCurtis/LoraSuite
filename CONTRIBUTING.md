# Contributing

Start with the setup in README.md. Use a feature branch and a focused pull request describing the problem, behavior change, and verification.

- Preserve project data and require an explicit user action before applying media or identity decisions.
- Keep Guided and Advanced on the same catalog, project records and engine operations.
- Treat LoRA Manager and ComfyUI as independent applications.
- Never commit credentials, vaults, personal datasets, generated model weights or internal audit evidence.
- Use synthetic fixtures and a temporary vault for tests. Do not invoke paid providers in automated tests.
- Run `npm test`, `npm run engine:test`, `npm run build`, and relevant Rust/companion checks.
- Qualify real provider execution separately from local contract tests.

By submitting a contribution, you agree that it is licensed under the repository's Apache-2.0 license. You must have the rights to submit it. Report security issues through the process in SECURITY.md.
