import type { EngineClient } from "../lib/api";
import { useState } from "react";

interface ExportsTabProps {
  engine: EngineClient;
}

export function ExportsTab({ engine }: ExportsTabProps) {
  const [framesText, setFramesText] = useState("");
  const [outputDir, setOutputDir] = useState("");
  const [captionTemplate, setCaptionTemplate] = useState("trigger_token, clean portrait");
  const [status, setStatus] = useState("Idle");

  async function createExport() {
    const frames = framesText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);

    if (frames.length === 0 || outputDir.trim() === "") {
      setStatus("Frame paths and output folder are required.");
      return;
    }

    setStatus("Exporting");
    try {
      const result = await engine.exportRunComfyImage({
        frames,
        output_dir: outputDir.trim(),
        caption_template: captionTemplate,
        source_segment_ids: [],
      });
      setStatus(`Export ${result.status}: ${result.output_path}`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Export failed.");
    }
  }

  return (
    <section className="workspace-section">
      <div className="section-header">
        <h2>Exports</h2>
        <p>Create RunComfy AI Toolkit image dataset folders.</p>
      </div>

      <div className="form-stack">
        <label htmlFor="frame-paths">Frame paths</label>
        <textarea
          id="frame-paths"
          value={framesText}
          onChange={(event) => setFramesText(event.target.value)}
          rows={6}
          placeholder="/absolute/path/to/frame.png"
        />

        <label htmlFor="output-folder">Output folder</label>
        <input
          id="output-folder"
          value={outputDir}
          onChange={(event) => setOutputDir(event.target.value)}
        />

        <label htmlFor="caption-template">Caption template</label>
        <input
          id="caption-template"
          value={captionTemplate}
          onChange={(event) => setCaptionTemplate(event.target.value)}
        />

        <button className="primary-action" type="button" onClick={createExport}>
          Create RunComfy Image Export
        </button>
        <p aria-live="polite" className="status-line">
          {status}
        </p>
      </div>
    </section>
  );
}
