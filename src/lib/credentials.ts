import { invoke, isTauri } from "@tauri-apps/api/core";

export type CredentialId =
  | "runcomfy_api"
  | "runpod_api"
  | "runpod_s3_access"
  | "runpod_s3_secret"
  | "huggingface_token"
  | "openai_api"
  | "xai_api"
  | "kimi_code_api"
  | "moonshot_api";

export interface CredentialDefinition {
  id: CredentialId;
  label: string;
  provider: string;
  environmentVariable: string;
}

export interface CredentialStatus {
  id: CredentialId;
  stored: boolean;
}

export const credentialDefinitions: CredentialDefinition[] = [
  { id: "runcomfy_api", label: "API token", provider: "RunComfy", environmentVariable: "RUNCOMFY_TOKEN" },
  { id: "runpod_api", label: "API key", provider: "RunPod", environmentVariable: "RUNPOD_API_KEY" },
  { id: "runpod_s3_access", label: "S3 access key", provider: "RunPod", environmentVariable: "AWS_ACCESS_KEY_ID" },
  { id: "runpod_s3_secret", label: "S3 secret key", provider: "RunPod", environmentVariable: "AWS_SECRET_ACCESS_KEY" },
  { id: "huggingface_token", label: "Model access token", provider: "Hugging Face", environmentVariable: "HF_TOKEN" },
  { id: "openai_api", label: "API key", provider: "OpenAI", environmentVariable: "OPENAI_API_KEY" },
  { id: "xai_api", label: "API key", provider: "Grok", environmentVariable: "XAI_API_KEY" },
  { id: "kimi_code_api", label: "API key", provider: "Kimi Code", environmentVariable: "KIMI_CODE_API_KEY" },
  { id: "moonshot_api", label: "API key", provider: "Kimi Platform", environmentVariable: "MOONSHOT_API_KEY" },
];

const sessionCredentials = new Map<CredentialId, string>();
const credentialEvent = "lorasuite:credentials-changed";
const credentialVaultOpenEvent = "lorasuite:open-credentials";

export function credentialStorageLabel(): string {
  return isDesktopRuntime() ? "System credential store" : "This browser session";
}

export async function getCredentialStatus(id: CredentialId): Promise<CredentialStatus> {
  if (!isDesktopRuntime()) {
    return { id, stored: sessionCredentials.has(id) };
  }
  return invoke<CredentialStatus>("credential_status", { id });
}

export async function getCredential(id: CredentialId): Promise<string | undefined> {
  if (!isDesktopRuntime()) {
    return sessionCredentials.get(id);
  }
  return (await invoke<string | null>("credential_get", { id })) ?? undefined;
}

export async function resolveCredential(
  id: CredentialId,
  explicitValue?: string | null,
): Promise<string | undefined> {
  const explicit = explicitValue?.trim();
  return explicit || await getCredential(id);
}

export async function setCredential(id: CredentialId, secret: string): Promise<CredentialStatus> {
  const value = secret.trim();
  if (!value) throw new Error("Credential value cannot be empty.");
  const status = isDesktopRuntime()
    ? await invoke<CredentialStatus>("credential_set", { id, secret: value })
    : storeSessionCredential(id, value);
  notifyCredentialChanged(id);
  return status;
}

export async function deleteCredential(id: CredentialId): Promise<CredentialStatus> {
  const status = isDesktopRuntime()
    ? await invoke<CredentialStatus>("credential_delete", { id })
    : deleteSessionCredential(id);
  notifyCredentialChanged(id);
  return status;
}

export function credentialIdForVisionProvider(providerId: string): CredentialId | undefined {
  if (providerId === "openai") return "openai_api";
  if (providerId === "grok") return "xai_api";
  if (providerId === "kimi_code") return "kimi_code_api";
  if (providerId === "kimi_platform") return "moonshot_api";
  return undefined;
}

export function subscribeToCredentialChanges(
  listener: (id: CredentialId) => void,
): () => void {
  const handler = (event: Event) => {
    const id = (event as CustomEvent<CredentialId>).detail;
    if (id) listener(id);
  };
  window.addEventListener(credentialEvent, handler);
  return () => window.removeEventListener(credentialEvent, handler);
}

export function openCredentialVault(id?: CredentialId): void {
  window.dispatchEvent(new CustomEvent<CredentialId | undefined>(
    credentialVaultOpenEvent,
    { detail: id },
  ));
}

export function subscribeToCredentialVaultRequests(
  listener: (id?: CredentialId) => void,
): () => void {
  const handler = (event: Event) => {
    listener((event as CustomEvent<CredentialId | undefined>).detail);
  };
  window.addEventListener(credentialVaultOpenEvent, handler);
  return () => window.removeEventListener(credentialVaultOpenEvent, handler);
}

function isDesktopRuntime(): boolean {
  try {
    return isTauri();
  } catch {
    return false;
  }
}

function storeSessionCredential(id: CredentialId, secret: string): CredentialStatus {
  sessionCredentials.set(id, secret);
  return { id, stored: true };
}

function deleteSessionCredential(id: CredentialId): CredentialStatus {
  sessionCredentials.delete(id);
  return { id, stored: false };
}

function notifyCredentialChanged(id: CredentialId): void {
  window.dispatchEvent(new CustomEvent<CredentialId>(credentialEvent, { detail: id }));
}
