import { RotateCcw, SlidersHorizontal } from "lucide-react";
import { useMemo } from "react";
import { parseDocument } from "yaml";

type TrainingSettingKey = "steps" | "rank" | "learningRate" | "saveEvery";

interface TrainingYamlSettings {
  steps: number;
  rank: number;
  learningRate: number;
  saveEvery: number;
}

interface TrainingSettingsPanelProps {
  configFile: string;
  defaultConfigFile: string;
  disabled?: boolean;
  onChange(configFile: string): void;
  onError?(message: string): void;
}

const settingPaths: Record<TrainingSettingKey, Array<string | number>> = {
  steps: ["config", "process", 0, "train", "steps"],
  rank: ["config", "process", 0, "network", "linear"],
  learningRate: ["config", "process", 0, "train", "lr"],
  saveEvery: ["config", "process", 0, "save", "save_every"],
};

export function TrainingSettingsPanel({
  configFile,
  defaultConfigFile,
  disabled = false,
  onChange,
  onError,
}: TrainingSettingsPanelProps) {
  const settings = useMemo(() => trainingSettingsFromYaml(configFile), [configFile]);
  if (!settings) return null;

  function update(key: TrainingSettingKey, value: number) {
    try {
      onChange(withTrainingSetting(configFile, key, value));
    } catch (error) {
      onError?.(errorMessage(error));
    }
  }

  return (
    <section className="training-basic-settings" aria-label="Training settings">
      <header>
        <SlidersHorizontal size={14} aria-hidden="true" />
        <strong>Training settings</strong>
        <small>YAML synced</small>
        <button
          type="button"
          title="Reset training settings to recipe defaults"
          aria-label="Reset training settings"
          disabled={disabled || configFile === defaultConfigFile}
          onClick={() => onChange(defaultConfigFile)}
        >
          <RotateCcw size={13} aria-hidden="true" />
        </button>
      </header>
      <div>
        <label>
          Steps
          <input
            aria-label="Training steps"
            type="number"
            min={250}
            max={10000}
            step={250}
            value={settings.steps}
            disabled={disabled}
            onChange={(event) => updateInteger(event.currentTarget.valueAsNumber, "steps", update)}
          />
        </label>
        <label>
          LoRA rank
          <select
            aria-label="LoRA rank"
            value={settings.rank}
            disabled={disabled}
            onChange={(event) => update("rank", Number(event.currentTarget.value))}
          >
            {rankOptions(settings.rank).map((rank) => <option key={rank} value={rank}>{rank}</option>)}
          </select>
        </label>
        <label>
          Learning rate
          <input
            aria-label="Learning rate"
            type="number"
            min={0.000001}
            max={0.01}
            step={0.00001}
            value={settings.learningRate}
            disabled={disabled}
            onChange={(event) => updatePositive(event.currentTarget.valueAsNumber, "learningRate", update)}
          />
        </label>
        <label>
          Checkpoint every
          <input
            aria-label="Checkpoint interval"
            type="number"
            min={50}
            max={5000}
            step={50}
            value={settings.saveEvery}
            disabled={disabled}
            onChange={(event) => updateInteger(event.currentTarget.valueAsNumber, "saveEvery", update)}
          />
        </label>
      </div>
    </section>
  );
}

export function trainingSettingsFromYaml(configFile: string): TrainingYamlSettings | null {
  try {
    const document = parseDocument(configFile, { prettyErrors: false });
    if (document.errors.length) return null;
    const settings = {
      steps: numberAt(document.getIn(settingPaths.steps)),
      rank: numberAt(document.getIn(settingPaths.rank)),
      learningRate: numberAt(document.getIn(settingPaths.learningRate)),
      saveEvery: numberAt(document.getIn(settingPaths.saveEvery)),
    };
    return Object.values(settings).every((value) => value !== null)
      ? settings as TrainingYamlSettings
      : null;
  } catch {
    return null;
  }
}

export function withTrainingSetting(
  configFile: string,
  key: TrainingSettingKey,
  value: number,
): string {
  if (!Number.isFinite(value) || value <= 0) throw new Error("Training values must be positive numbers.");
  const document = parseDocument(configFile, { prettyErrors: false });
  if (document.errors.length) throw new Error(document.errors[0]?.message ?? "The AI Toolkit YAML is invalid.");
  const path = settingPaths[key];
  if (document.getIn(path) == null) throw new Error(`The selected recipe does not expose ${key}.`);
  if (key === "steps" || key === "rank" || key === "saveEvery") value = Math.round(value);
  if (key === "rank") {
    document.setIn(["config", "process", 0, "network", "linear_alpha"], value);
  }
  document.setIn(path, value);
  return document.toString({ lineWidth: 0 });
}

function numberAt(value: unknown): number | null {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function rankOptions(current: number): number[] {
  return [...new Set([8, 16, 32, 64, 128, current])].sort((left, right) => left - right);
}

function updateInteger(
  value: number,
  key: "steps" | "saveEvery",
  update: (key: TrainingSettingKey, value: number) => void,
) {
  if (Number.isFinite(value) && value > 0) update(key, Math.round(value));
}

function updatePositive(
  value: number,
  key: "learningRate",
  update: (key: TrainingSettingKey, value: number) => void,
) {
  if (Number.isFinite(value) && value > 0) update(key, value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
