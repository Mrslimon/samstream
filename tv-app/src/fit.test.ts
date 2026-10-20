import { describe, expect, it } from "vitest";
import { loadFit, nextFit, saveFit } from "./fit";
import { supportedCodecs } from "./mse";

describe("fit modes", () => {
  it("cycles both ways", () => {
    expect(nextFit("contain", 1)).toBe("cover");
    expect(nextFit("fill", 1)).toBe("contain");
    expect(nextFit("contain", -1)).toBe("fill");
  });

  it("persists the choice and ignores junk", () => {
    saveFit("fill");
    expect(loadFit()).toBe("fill");
    localStorage.setItem("samstream.fit", "zoom");
    expect(loadFit()).toBe("contain");
  });
});

describe("supportedCodecs", () => {
  it("offers only what the platform can decode", () => {
    const codecs = supportedCodecs((type) => type.includes("avc1") || type.includes("flac"));
    expect(codecs).toContain("avc1.640033");
    expect(codecs).toContain("flac");
    expect(codecs).not.toContain("hvc1.1.6.L153.B0");
  });
});
