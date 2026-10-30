import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { appThemes, isAppTheme, ThemePicker } from "./ThemePicker";

describe("ThemePicker", () => {
  it("offers twelve complete theme families", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ThemePicker theme="aurora" onChange={onChange} />);

    expect(appThemes).toHaveLength(12);
    expect(new Set(appThemes.map((theme) => theme.id)).size).toBe(12);

    await user.click(screen.getByLabelText("Choose color theme"));
    for (const theme of appThemes) {
      expect(screen.getByRole("button", { name: theme.label })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("button", { name: "Synthwave" }));
    expect(onChange).toHaveBeenCalledWith("synthwave");
  });

  it("recognizes every persisted theme and rejects unknown values", () => {
    for (const theme of appThemes) {
      expect(isAppTheme(theme.id)).toBe(true);
    }
    expect(isAppTheme("green-but-not-a-theme")).toBe(false);
    expect(isAppTheme(null)).toBe(false);
  });
});
