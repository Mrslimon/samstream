import { describe, expect, it } from "vitest";
import { showOverlay } from "./overlay";

describe("showOverlay", () => {
  it("replaces previous content and lets the text choose its direction", () => {
    const container = document.createElement("div");
    showOverlay(container, "old");
    const message = showOverlay(container, "الاستئناف خلال 3 ثوانٍ");

    expect(container.children).toHaveLength(1);
    expect(message.dir).toBe("auto");
    expect(message.textContent).toBe("الاستئناف خلال 3 ثوانٍ");
  });
});
