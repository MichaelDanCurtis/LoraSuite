import type { CharacterProject } from "./types";

export function projectOptionLabel(project: CharacterProject): string {
  const name = project.name?.trim() || "Character Dataset";
  const subject = project.intent?.subject_name?.trim() || "";
  if (subject && subject.toLocaleLowerCase() !== name.toLocaleLowerCase()) {
    return `${name} · ${subject}`;
  }
  return `${name} · ${project.id?.slice(-6) || "unknown"}`;
}
