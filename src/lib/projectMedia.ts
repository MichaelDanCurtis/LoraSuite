import type { MediaItem } from "./types";
import type { WizardTarget } from "../components/WorkflowWizard";

export function isRelevantMedia(item: MediaItem, target: WizardTarget): boolean {
  if (item.status === "ignored") return false;
  if (target === "image" || target === "video") return item.media_type === "image" || item.media_type === "video";
  if (target === "voice") return item.media_type === "audio" || item.media_type === "video";
  return true;
}
