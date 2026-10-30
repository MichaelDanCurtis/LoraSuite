import type { TrainingTargetProfile } from "./types";
import type { WizardTarget } from "../components/WorkflowWizard";

export const defaultTrainingTargetProfileIds: Record<WizardTarget, string> = {
  image: "runcomfy_flux1_dev_character", video: "runcomfy_wan22_14b_t2v_character",
  voice: "runpod_fish_speech_s2_voice_lora", id_lora: "runpod_id_lora_ltx23_inference",
};
const modality = { image: "image", video: "video", voice: "voice", id_lora: "audio_visual" } as const;
export function targetsForOutput(targets: TrainingTargetProfile[], output: WizardTarget) {
  // The current living-identity compiler exports the zero-shot manifest only.
  return targets.filter((target) => (target.modality ?? "image") === modality[output]
    && (output !== "id_lora" || target.profile_id === defaultTrainingTargetProfileIds.id_lora));
}
export function trainingTargetLabel(target: TrainingTargetProfile) {
  return `${target.label}${target.recipe?.status === "experimental" ? " · Experimental" : ""}`;
}
