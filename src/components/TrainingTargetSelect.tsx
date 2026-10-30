import type { TrainingTargetProfile } from "../lib/types";
import { targetsForOutput, trainingTargetLabel } from "../lib/trainingCatalog";
import type { WizardTarget } from "./WorkflowWizard";

export function TrainingTargetSelect({ targets, output, value, onChange, label = "Model recipe", disabled = false }: {
  targets: TrainingTargetProfile[]; output: WizardTarget; value: string;
  onChange(value: string): void; label?: string; disabled?: boolean;
}) {
  const options = targetsForOutput(targets, output);
  return <select aria-label={label} value={value} disabled={disabled || !options.length} onChange={(event) => onChange(event.target.value)}>
    {!options.some((target) => target.profile_id === value) ? <option value={value}>{options.length ? "Choose a compatible recipe" : "Loading model recipes…"}</option> : null}
    {options.map((target) => <option key={target.profile_id} value={target.profile_id}>{trainingTargetLabel(target)}</option>)}
  </select>;
}
