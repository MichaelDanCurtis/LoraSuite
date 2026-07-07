import type { EngineClient } from "../lib/api";

interface ExportsTabProps {
  engine: EngineClient;
}

export function ExportsTab(_props: ExportsTabProps) {
  return (
    <section className="workspace-section">
      <div className="section-header">
        <h2>Exports</h2>
        <p>Create RunComfy AI Toolkit image dataset folders.</p>
      </div>
      <p className="muted">RunComfy image export controls are staged for the next UI slice.</p>
    </section>
  );
}
