import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { parseDocument } from "yaml";

import {
  TrainingSettingsPanel,
  trainingSettingsFromYaml,
  withTrainingSetting,
} from "./TrainingSettingsPanel";

describe("TrainingSettingsPanel", () => {
  it("keeps basic controls synchronized with the AI Toolkit YAML", () => {
    render(<TrainingSettingsHarness />);

    fireEvent.change(screen.getByLabelText("Training steps"), { target: { value: "3000" } });
    fireEvent.change(screen.getByLabelText("LoRA rank"), { target: { value: "64" } });
    fireEvent.change(screen.getByLabelText("Learning rate"), { target: { value: "0.0002" } });
    fireEvent.change(screen.getByLabelText("Checkpoint interval"), { target: { value: "500" } });

    const config = screen.getByTestId("training-config").textContent ?? "";
    expect(trainingSettingsFromYaml(config)).toEqual({
      steps: 3000,
      rank: 64,
      learningRate: 0.0002,
      saveEvery: 500,
    });
    expect(parseDocument(config).getIn(["config", "process", 0, "network", "linear_alpha"])).toBe(64);
  });

  it("resets the generated YAML to the recipe defaults", () => {
    render(<TrainingSettingsHarness />);

    fireEvent.change(screen.getByLabelText("Training steps"), { target: { value: "3500" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset training settings" }));

    expect(screen.getByTestId("training-config").textContent).toBe(DEFAULT_CONFIG);
    expect(screen.getByLabelText("Training steps")).toHaveValue(2000);
  });

  it("does not guess settings for an unsupported YAML shape", () => {
    expect(trainingSettingsFromYaml("folder_path: /dataset")).toBeNull();
    expect(() => withTrainingSetting("folder_path: /dataset", "steps", 3000)).toThrow(
      "The selected recipe does not expose steps.",
    );
  });
});

function TrainingSettingsHarness() {
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  return (
    <>
      <TrainingSettingsPanel
        configFile={config}
        defaultConfigFile={DEFAULT_CONFIG}
        onChange={setConfig}
      />
      <pre data-testid="training-config">{config}</pre>
    </>
  );
}

const DEFAULT_CONFIG = `---
job: extension
config:
  name: person-krea2-v1
  process:
    - type: diffusion_trainer
      network:
        type: lora
        linear: 32
        linear_alpha: 32
      save:
        save_every: 250
      datasets:
        - folder_path: /app/ai-toolkit/datasets/{dataset_name}
      train:
        steps: 2000
        lr: 0.0001
      model:
        name_or_path: krea/Krea-2-Raw
        arch: krea2
`;
