/// <reference types="node" />

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const styles = readFileSync(join(process.cwd(), "src", "styles.css"), "utf8") + readFileSync(join(process.cwd(), "extensions/lorasuite-companion/themes.css"), "utf8");
const sphereRenderer = readFileSync(
  join(process.cwd(), "src", "components", "WarpedSphereSurface.tsx"),
  "utf8",
);

function cssRuleBody(selector: string): string {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`).exec(styles);
  return match?.[1] ?? "";
}

describe("styles.css", () => {
  it("keeps the ingress summary metrics compact on one row", () => {
    const headerRule = cssRuleBody(".ingress-header");
    const metricRule = cssRuleBody(".metric-grid");
    const metricBoxRule = cssRuleBody(".metric-grid div");

    expect(headerRule).toContain("grid-template-columns: minmax(260px, 1fr) auto;");
    expect(metricRule).toContain("grid-template-columns: repeat(4, minmax(72px, 92px));");
    expect(metricRule).toContain("justify-content: end;");
    expect(metricBoxRule).toContain("padding: 7px 8px;");
  });

  it("animates thumbnail hover previews smoothly and returns immediately", () => {
    const previewRule = cssRuleBody(".hover-preview");

    expect(previewRule).toContain("transform: translate(-50%, -44%) scale(0.92);");
    expect(previewRule).toContain(
      "transform 240ms cubic-bezier(0.34, 1.56, 0.64, 1)",
    );
    expect(styles).toContain("opacity 160ms ease 900ms");
    expect(styles).toContain("transform 220ms ease-out 900ms");
  });

  it("renders ineligible voice chips with a black background and grey text", () => {
    const rule = cssRuleBody(".role-chip.audio-ineligible:not(.selected)");

    expect(rule).toContain("background: #101820;");
    expect(rule).toContain("color: #aeb8b3;");
  });

  it("keeps all three top-header controls on one desktop row", () => {
    expect(styles).toContain(
      "grid-template-columns: auto minmax(120px, 1fr) auto;\n  height: 58px;",
    );
    expect(styles).toContain(".app-header > * {\n  min-width: 0;");
  });

  it("raises expanded source thumbnails and their controls above intake menus", () => {
    const fieldRule = cssRuleBody(".source-candidate-field:has(.source-candidate-bubble:focus-within)");
    const bubbleRule = cssRuleBody(".source-candidate-bubble:focus-within");
    const footerRule = cssRuleBody(".source-intake-footer");

    expect(fieldRule).toContain("overflow: visible;");
    expect(fieldRule).toContain("z-index: 30;");
    expect(bubbleRule).toContain("scale: 1.5;");
    expect(bubbleRule).toContain("z-index: 80;");
    expect(footerRule).toContain("position: relative;");
    expect(footerRule).toContain("z-index: 2;");
  });

  it("shows complete caption preview images without fixed-height clipping", () => {
    const livePreview = cssRuleBody(".guided-live-caption figure img");
    const decisionPreview = cssRuleBody(".guided-caption-image img");

    for (const rule of [livePreview, decisionPreview]) {
      expect(rule).toContain("height: auto;");
      expect(rule).toContain("max-height: min(70vh, 720px);");
      expect(rule).toContain("max-width: 100%;");
      expect(rule).toContain("object-fit: contain;");
      expect(rule).toContain("width: auto;");
      expect(rule).not.toContain("height: 100%;");
    }
  });

  it("defines a complete interface and rendered-space palette for every theme", () => {
    const themeMarkers = [
      ':root[data-theme="aurora"] {',
      ':root[data-theme="ocean"] {',
      ':root[data-theme="solar"] {',
      ':root[data-theme="graphite"] {',
      ':root[data-theme="nebula"] {',
      ':root[data-theme="rose"] {',
      ':root[data-theme="ember"] {',
      ':root[data-theme="arctic"] {',
      ':root[data-theme="midnight"] {',
      ':root[data-theme="copper"] {',
      ':root[data-theme="acid"] {',
      ':root[data-theme="synthwave"] {',
    ];

    for (const marker of themeMarkers) {
      const start = styles.indexOf(marker);
      expect(start).toBeGreaterThan(-1);
      const body = styles.slice(start, styles.indexOf("}", start));
      expect(body).toContain("--guided-bg-rgb:");
      expect(body).toContain("--guided-panel-rgb:");
      expect(body).toContain("--guided-warm-rgb:");
      expect(body).toContain("--latent-membrane-dark-rgb:");
      expect(body).toContain("--latent-membrane-light-rgb:");
      expect(body).toContain("--latent-line-primary-rgb:");
      expect(body).toContain("--latent-particle-secondary-rgb:");
    }
  });

  it("feeds theme colors into the workflow sphere", () => {
    expect(sphereRenderer).toContain('getPropertyValue("--guided-bg-rgb")');
    expect(sphereRenderer).toContain('attributeFilter: ["data-theme"]');
  });
});
