import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  // Unit tests must never reach a running desktop engine or mutate its vault.
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Network disabled in unit tests; provide a fetch mock.")));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
