import { describe, expect, it } from "vitest";
import {
  cameraList,
  initials,
  sectionsOf,
  tileColor,
  touchGesture,
  type Hass,
} from "./helpers";
import { LANGUAGES, languageOf, strings } from "./strings";

function hass(partial: Partial<Hass>): Hass {
  return {
    states: {},
    callService: async () => undefined,
    callWS: async () => undefined as never,
    ...partial,
  };
}

const state = (entity_id: string, name?: string) => ({
  entity_id,
  state: "on",
  attributes: name ? { friendly_name: name } : {},
});

describe("cameraList", () => {
  const h = hass({
    states: {
      "camera.b": state("camera.b", "Back yard"),
      "camera.a": state("camera.a", "Front door"),
      "light.x": state("light.x"),
    },
  });

  it("lists every camera by name when none are configured", () => {
    expect(cameraList(h, undefined)).toEqual(["camera.b", "camera.a"]);
  });

  it("keeps the configured order and drops missing ones", () => {
    expect(cameraList(h, ["camera.a", "camera.gone", "camera.b"])).toEqual(["camera.a", "camera.b"]);
  });
});

describe("tiles", () => {
  it("uses one Arabic letter or two Latin initials", () => {
    expect(initials("شاهد MBC")).toBe("ش");
    expect(initials("Apple TV")).toBe("AT");
    expect(initials("YouTube")).toBe("Y");
    expect(initials("  ")).toBe("?");
  });

  it("gives each name a stable colour", () => {
    expect(tileColor("Netflix")).toBe(tileColor("Netflix"));
    expect(tileColor("Netflix")).toMatch(/^hsl\(\d+ 55% 46%\)$/);
  });
});

describe("strings", () => {
  it("picks Arabic for any ar locale", () => {
    expect(languageOf("ar-EG")).toBe("ar");
    expect(languageOf("en-GB")).toBe("en");
    expect(languageOf(undefined)).toBe("en");
  });

  it("has the same keys in every language", () => {
    const keys = Object.keys(strings("en")).sort();
    for (const language of LANGUAGES) expect(Object.keys(strings(language)).sort()).toEqual(keys);
  });
});

describe("sectionsOf", () => {
  it("keeps the chosen order and drops unknown or repeated ones", () => {
    expect(sectionsOf({ sections: ["remote", "media", "remote", "x"] })).toEqual(["remote", "media"]);
    expect(sectionsOf({ sections: [] })).toEqual([]);
  });

  it("reads the switches of cards made before sections existed", () => {
    expect(sectionsOf({})).toEqual(["tv", "cameras", "message", "apps", "remote", "media"]);
    expect(sectionsOf({ show_cameras: false, show_remote: false })).toEqual(["tv", "message", "apps"]);
  });
});

describe("touchGesture", () => {
  it("tells taps, long presses and drags apart", () => {
    expect(touchGesture(2, 120)).toBe("click");
    expect(touchGesture(3, 900)).toBe("right");
    expect(touchGesture(40, 120)).toBe("move");
    expect(touchGesture(2, 450)).toBe("move");
  });
});
