import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const credentialMocks = vi.hoisted(() => ({
  getCredentialStatus: vi.fn(),
  setCredential: vi.fn(),
  deleteCredential: vi.fn(),
}));

vi.mock("../lib/credentials", async (importOriginal) => {
  const original = await importOriginal<typeof import("../lib/credentials")>();
  return {
    ...original,
    credentialStorageLabel: () => "System credential store",
    getCredentialStatus: credentialMocks.getCredentialStatus,
    setCredential: credentialMocks.setCredential,
    deleteCredential: credentialMocks.deleteCredential,
  };
});

import { CredentialVault } from "./CredentialVault";
import { openCredentialVault } from "../lib/credentials";

describe("CredentialVault", () => {
  beforeEach(() => {
    credentialMocks.getCredentialStatus.mockReset();
    credentialMocks.setCredential.mockReset();
    credentialMocks.deleteCredential.mockReset();
    credentialMocks.getCredentialStatus.mockImplementation(async (id: string) => ({
      id,
      stored: id === "runcomfy_api",
    }));
    credentialMocks.setCredential.mockImplementation(async (id: string) => ({ id, stored: true }));
    credentialMocks.deleteCredential.mockImplementation(async (id: string) => ({ id, stored: false }));
  });

  it("saves a new secret without displaying a stored value", async () => {
    const user = userEvent.setup();
    render(<CredentialVault />);

    await user.click(screen.getByRole("button", { name: "Credentials" }));
    await waitFor(() => expect(screen.getByText("System credential store")).toBeInTheDocument());
    expect(screen.getByLabelText("RunComfy API token")).toHaveValue("");
    expect(screen.getByLabelText("RunComfy API token")).toHaveAttribute("placeholder", "Stored securely");

    const input = screen.getByLabelText("RunPod API key");
    await user.type(input, "runpod-secret");
    await user.click(screen.getByTitle("Save RunPod API key"));

    expect(credentialMocks.setCredential).toHaveBeenCalledWith("runpod_api", "runpod-secret");
    expect(input).toHaveValue("");
    expect(screen.getByText(/Saved to system credential store/)).toBeInTheDocument();
  });

  it("forgets an existing credential", async () => {
    const user = userEvent.setup();
    render(<CredentialVault />);

    await user.click(screen.getByRole("button", { name: "Credentials" }));
    await user.click(await screen.findByTitle("Forget RunComfy API token"));

    expect(credentialMocks.deleteCredential).toHaveBeenCalledWith("runcomfy_api");
    expect(screen.getByText("Credential removed.")).toBeInTheDocument();
  });

  it("opens from a provider onboarding request", async () => {
    render(<CredentialVault />);

    openCredentialVault("runpod_api");

    expect(await screen.findByLabelText("Provider credentials")).toBeInTheDocument();
  });

  it("closes from the modal backdrop", async () => {
    const user = userEvent.setup();
    render(<CredentialVault />);

    await user.click(screen.getByRole("button", { name: "Credentials" }));
    await user.click(screen.getByRole("button", { name: "Close provider credentials" }));

    expect(screen.queryByLabelText("Provider credentials")).not.toBeInTheDocument();
  });
});
