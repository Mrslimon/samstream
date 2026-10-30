import { describe, expect, it } from "vitest";
import {
  MAX_ZOOM,
  coverCrop,
  matteId,
  matteInset,
  panCrop,
  parseMatte,
  sharpness,
  uploadTarget,
  zoomCrop,
} from "./art-helpers";

describe("coverCrop", () => {
  it("takes the full width of a tall picture, centred", () => {
    expect(coverCrop(3000, 4000)).toEqual({ x: 0, y: (4000 - 1687.5) / 2, width: 3000, height: 1687.5 });
  });
  it("takes the full height of a wide picture, centred", () => {
    const crop = coverCrop(8000, 2160);
    expect(crop.width).toBe(3840);
    expect(crop.x).toBe((8000 - 3840) / 2);
  });
});

describe("zoom and pan", () => {
  const start = coverCrop(4000, 3000);
  it("zooms around the centre and stays screen-shaped", () => {
    const zoomed = zoomCrop(start, 4000, 3000, 2);
    expect(zoomed.width).toBeCloseTo(start.width / 2);
    expect(zoomed.width / zoomed.height).toBeCloseTo(16 / 9);
    expect(zoomed.x + zoomed.width / 2).toBeCloseTo(2000);
  });
  it("caps the zoom", () => {
    expect(zoomCrop(start, 4000, 3000, 99).width).toBeCloseTo(start.width / MAX_ZOOM);
    expect(zoomCrop(start, 4000, 3000, 0.1).width).toBeCloseTo(start.width);
  });
  it("never leaves the picture", () => {
    const zoomed = zoomCrop(start, 4000, 3000, 2);
    const moved = panCrop(zoomed, -99999, 99999, 4000, 3000);
    expect(moved.x).toBe(0);
    expect(moved.y + moved.height).toBeCloseTo(3000);
  });
});

describe("sharpness", () => {
  it("rates the crop against the 4K screen", () => {
    expect(sharpness({ x: 0, y: 0, width: 3840, height: 2160 })).toBe("sharp");
    expect(sharpness({ x: 0, y: 0, width: 2400, height: 1350 })).toBe("fine");
    expect(sharpness({ x: 0, y: 0, width: 1000, height: 562 })).toBe("soft");
  });
});

describe("mattes", () => {
  it("builds and splits border ids", () => {
    expect(matteId("shadowbox", "sand")).toBe("shadowbox_sand");
    expect(matteId("none", "sand")).toBe("none");
    expect(matteId("modern", "")).toBe("none");
    expect(parseMatte("shadowbox_sand")).toEqual({ style: "shadowbox", colour: "sand" });
    expect(parseMatte("none")).toEqual({ style: "none", colour: "" });
    expect(parseMatte(undefined)).toEqual({ style: "none", colour: "" });
  });
  it("gives every style a preview inset", () => {
    expect(matteInset("none")).toBe(0);
    expect(matteInset("modernwide")).toBeGreaterThan(matteInset("modernthin"));
    expect(matteInset("future-style")).toBeGreaterThan(0);
  });
  it("puts the border and show flag in the upload address", () => {
    expect(uploadTarget("/api/samstream/art_upload/e1", "shadowbox_sand", true)).toBe(
      "/api/samstream/art_upload/e1?matte=shadowbox_sand&show=1",
    );
    expect(uploadTarget("/u", "none", false)).toBe("/u?matte=none");
  });
});
