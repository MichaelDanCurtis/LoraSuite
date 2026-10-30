import { Check, Palette } from "lucide-react";

export const appThemes = [
  { id: "aurora", label: "Aurora", colors: ["#62e6ae", "#5bc9e8", "#e4b85f"] },
  { id: "ocean", label: "Ocean", colors: ["#47c9d4", "#76a8ea", "#b7e36a"] },
  { id: "solar", label: "Solar", colors: ["#f0b35b", "#e36e5b", "#6bd2b2"] },
  { id: "graphite", label: "Graphite", colors: ["#d8dfdc", "#8ea39a", "#f0c875"] },
  { id: "nebula", label: "Nebula", colors: ["#b58cff", "#e56fd8", "#74d9e8"] },
  { id: "rose", label: "Rose", colors: ["#ff86aa", "#d8a0ff", "#ffc06a"] },
  { id: "ember", label: "Ember", colors: ["#ff785c", "#ffb45f", "#ffd36a"] },
  { id: "arctic", label: "Arctic", colors: ["#9ee9ff", "#b9cfff", "#e8fdff"] },
  { id: "midnight", label: "Midnight", colors: ["#738cff", "#65d4ff", "#c7a7ff"] },
  { id: "copper", label: "Copper", colors: ["#d69b68", "#7fc6b1", "#f0c27b"] },
  { id: "acid", label: "Acid", colors: ["#b9f45a", "#64e3c1", "#f5df5f"] },
  { id: "synthwave", label: "Synthwave", colors: ["#ff66d4", "#57e8ff", "#ffe16b"] },
] as const;

export type AppTheme = (typeof appThemes)[number]["id"];

export function isAppTheme(value: string | null): value is AppTheme {
  return appThemes.some((theme) => theme.id === value);
}

interface ThemePickerProps {
  theme: AppTheme;
  onChange(theme: AppTheme): void;
  syncError?: string;
}

export function ThemePicker({ theme, onChange, syncError }: ThemePickerProps) {
  return (
    <details className="theme-picker">
      <summary aria-label="Choose color theme" title="Choose color theme">
        <Palette size={16} aria-hidden="true" />
      </summary>
      <div className="theme-picker-menu" role="group" aria-label="Color theme">
        <header>
          <strong>Color theme</strong>
          <small>Shared with LoraSuite and the companion</small>
          {syncError ? <small role="status">{syncError}</small> : null}
        </header>
        {appThemes.map((option) => (
          <button
            key={option.id}
            type="button"
            aria-pressed={theme === option.id}
            onClick={(event) => {
              onChange(option.id);
              event.currentTarget.closest("details")?.removeAttribute("open");
            }}
          >
            <span className="theme-swatches" aria-hidden="true">
              {option.colors.map((color) => <i key={color} style={{ background: color }} />)}
            </span>
            <span>{option.label}</span>
            {theme === option.id ? <Check size={14} aria-hidden="true" /> : null}
          </button>
        ))}
      </div>
    </details>
  );
}
