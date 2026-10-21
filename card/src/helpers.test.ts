import { describe, expect, it } from "vitest";
import { cameraList, initials, remoteEntity, sectionsOf, tileColor, type Hass } from "./helpers";
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

describe("remoteEntity", () => {
  it("finds the remote on the same device", () => {
    const h = hass({
      entities: {
        "media_player.tv": { entity_id: "media_player.tv", device_id: "d1" },
        "remote.other": { entity_id: "remote.other", device_id: "d2" },
        "remote.living_room": { entity_id: "remote.living_room", device_id: "d1" },
      },
    });
    expect(remoteEntity(h, "media_player.tv")).toBe("remote.living_room");
  });

  it("falls back to the same object ID", () => {
    const h = hass({ states: { "remote.tv": state("remote.tv") } });
    expect(remoteEntity(h, "media_player.tv")).toBe("remote.tv");
    expect(remoteEntity(hass({}), "media_player.tv")).toBeUndefined();
  });
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
