import { describe, expect, it } from "vitest";
import { loadSettings, normalizeSettings, type Fetch, type SettingsStore } from "./settings";

const CONFIG = JSON.stringify({
  ha_url: "http://192.168.1.5:8123/",
  tv_secret: "s3cr3t",
  settings: { language: "en", theme: "dark" },
});
const SETTINGS_URL = "http://192.168.1.5:8123/api/samstream/tv/s3cr3t/settings";

function fakeFetch(answers: Record<string, string | Error>): Fetch {
  return async (url) => {
    const answer = answers[url];
    if (answer === undefined || answer instanceof Error) throw answer ?? new Error("404");
    return answer;
  };
}

function memoryStore(initial: Record<string, string> = {}): SettingsStore & { data: Record<string, string> } {
  const data = { ...initial };
  return { data, getItem: (key) => data[key] ?? null, setItem: (key, value) => (data[key] = value) };
}

describe("normalizeSettings", () => {
  it("keeps known values only", () => {
    expect(normalizeSettings({ language: "ar", theme: "light", extra: 1 })).toEqual({
      language: "ar",
      theme: "light",
    });
    expect(normalizeSettings({ language: "fr", theme: "neon" })).toEqual({});
    expect(normalizeSettings(null)).toEqual({});
  });
});

describe("loadSettings", () => {
  it("uses Home Assistant's answer and caches it", async () => {
    const store = memoryStore();
    const loaded = await loadSettings(
      fakeFetch({ "samstream.json": CONFIG, [SETTINGS_URL]: '{"language":"ar","theme":"light"}' }),
      store,
    );
    expect(loaded.source).toBe("home-assistant");
    expect(loaded.settings).toEqual({ language: "ar", theme: "light" });
    expect(JSON.parse(store.data["samstream.settings"])).toEqual({ language: "ar", theme: "light" });
  });

  it("falls back to the cache when Home Assistant is unreachable", async () => {
    const store = memoryStore({ "samstream.settings": '{"language":"ar"}' });
    const loaded = await loadSettings(
      fakeFetch({ "samstream.json": CONFIG, [SETTINGS_URL]: new Error("timeout") }),
      store,
    );
    expect(loaded.source).toBe("cache");
    expect(loaded.settings).toEqual({ language: "ar", theme: "dark" });
  });

  it("uses the package's copy without a cache", async () => {
    const loaded = await loadSettings(fakeFetch({ "samstream.json": CONFIG }), memoryStore());
    expect(loaded.source).toBe("package");
    expect(loaded.settings).toEqual({ language: "en", theme: "dark" });
    expect(loaded.config?.tv_secret).toBe("s3cr3t");
  });

  it("defaults for a build not installed by Home Assistant", async () => {
    const loaded = await loadSettings(fakeFetch({}), undefined);
    expect(loaded).toEqual({
      settings: { language: "auto", theme: "light" },
      config: undefined,
      source: "default",
    });
  });
});
