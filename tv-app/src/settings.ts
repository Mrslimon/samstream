/**
 * TV app settings chosen in Home Assistant (Samstream → Configure → TV app).
 *
 * HA writes `samstream.json` (its URL + this TV's secret) into the package when it
 * installs the app. On start the app asks HA for the current settings; if HA is
 * unreachable it uses the last answer it got, then the package's copy.
 */

export type LanguageSetting = "auto" | "ar" | "en";
export type Theme = "light" | "dark";

export interface TvSettings {
  language: LanguageSetting;
  theme: Theme;
}

export interface PackageConfig {
  ha_url: string;
  tv_secret: string;
  settings?: Partial<TvSettings>;
}

export type Fetch = (url: string, timeoutMs: number) => Promise<string>;

export interface SettingsStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

export const DEFAULT_SETTINGS: TvSettings = { language: "auto", theme: "light" };
const CACHE_KEY = "samstream.settings";
const HA_TIMEOUT_MS = 3_000;
const LANGUAGES: readonly LanguageSetting[] = ["auto", "ar", "en"];
const THEMES: readonly Theme[] = ["light", "dark"];

/** Keep only known values; anything else falls back to the defaults. */
export function normalizeSettings(raw: unknown): Partial<TvSettings> {
  if (typeof raw !== "object" || raw === null) {
    return {};
  }
  const { language, theme } = raw as Record<string, unknown>;
  const result: Partial<TvSettings> = {};
  if (LANGUAGES.includes(language as LanguageSetting)) result.language = language as LanguageSetting;
  if (THEMES.includes(theme as Theme)) result.theme = theme as Theme;
  return result;
}

function parseConfig(text: string): PackageConfig | undefined {
  try {
    const raw = JSON.parse(text) as Record<string, unknown>;
    if (typeof raw.ha_url === "string" && typeof raw.tv_secret === "string") {
      return {
        ha_url: raw.ha_url,
        tv_secret: raw.tv_secret,
        settings: normalizeSettings(raw.settings),
      };
    }
  } catch {
    // Not installed by Home Assistant (development build).
  }
  return undefined;
}

function readCache(store: SettingsStore | undefined): Partial<TvSettings> {
  try {
    return normalizeSettings(JSON.parse(store?.getItem(CACHE_KEY) ?? "null"));
  } catch {
    return {};
  }
}

export interface LoadedSettings {
  settings: TvSettings;
  config: PackageConfig | undefined;
  source: "home-assistant" | "cache" | "package" | "default";
}

export async function loadSettings(
  fetchText: Fetch,
  store: SettingsStore | undefined,
): Promise<LoadedSettings> {
  const config = await fetchText("samstream.json", HA_TIMEOUT_MS).then(parseConfig, () => undefined);
  const base = { ...DEFAULT_SETTINGS, ...config?.settings };
  if (config?.ha_url && config.tv_secret) {
    const url = `${config.ha_url.replace(/\/+$/, "")}/api/samstream/tv/${encodeURIComponent(config.tv_secret)}/settings`;
    try {
      const remote = normalizeSettings(JSON.parse(await fetchText(url, HA_TIMEOUT_MS)));
      try {
        store?.setItem(CACHE_KEY, JSON.stringify(remote));
      } catch {
        // Storage unavailable: still use the answer this time.
      }
      return { settings: { ...base, ...remote }, config, source: "home-assistant" };
    } catch {
      // HA unreachable: fall through to the cached answer.
    }
  }
  const cached = readCache(store);
  if (Object.keys(cached).length > 0) {
    return { settings: { ...base, ...cached }, config, source: "cache" };
  }
  return { settings: base, config, source: config ? "package" : "default" };
}

/** XHR works for both package files (file://) and HA (http://) on Tizen. */
export const xhrFetch: Fetch = (url, timeoutMs) =>
  new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("GET", url);
    request.timeout = timeoutMs;
    request.onload = () =>
      request.status === 200 || (request.status === 0 && request.responseText)
        ? resolve(request.responseText)
        : reject(new Error(`HTTP ${request.status}`));
    request.onerror = () => reject(new Error("network error"));
    request.ontimeout = () => reject(new Error("timeout"));
    request.send();
  });
