/**
 * TV app settings chosen in Home Assistant (Samstream → Configure → TV app).
 *
 * HA writes `samstream.json` (its URL + this TV's secret) into the package when it
 * installs the app. On start the app asks HA for the current settings; if HA is
 * unreachable it uses the last answer it got, then the package's copy.
 */

import { parseCameraList, type CameraStream } from "./streams";

export type LanguageSetting = "auto" | "ar" | "en";
export type Theme = "light" | "dark";

export interface TvSettings {
  language: LanguageSetting;
  theme: Theme;
  /** Configure → Cameras: what Left/Right flips between, ready at launch. */
  cameras: CameraStream[];
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

export const DEFAULT_SETTINGS: TvSettings = { language: "auto", theme: "light", cameras: [] };
const CACHE_KEY = "samstream.settings";
const HA_TIMEOUT_MS = 3_000;
const LANGUAGES: readonly LanguageSetting[] = ["auto", "ar", "en"];
const THEMES: readonly Theme[] = ["light", "dark"];

/** Keep only known values; anything else falls back to the defaults. */
export function normalizeSettings(raw: unknown): Partial<TvSettings> {
  if (typeof raw !== "object" || raw === null) {
    return {};
  }
  const { language, theme, cameras } = raw as Record<string, unknown>;
  const result: Partial<TvSettings> = {};
  if (LANGUAGES.includes(language as LanguageSetting)) result.language = language as LanguageSetting;
  if (THEMES.includes(theme as Theme)) result.theme = theme as Theme;
  if (cameras !== undefined) result.cameras = parseCameraList(cameras);
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

/** Command HA queued for this TV (`samstream.play_stream` / `stop_stream`). */
export interface Session {
  seq: number;
  command: unknown;
}

export interface LoadedSettings {
  settings: TvSettings;
  config: PackageConfig | undefined;
  source: "home-assistant" | "cache" | "package" | "default";
  session?: Session;
}

function sessionUrl(config: PackageConfig, since: number): string {
  const base = config.ha_url.replace(/\/+$/, "");
  return `${base}/api/samstream/tv/${encodeURIComponent(config.tv_secret)}/session?since=${since}`;
}

/** What happened to a command HA sent (its `seq`), reported with the next poll. */
export interface SessionReport {
  /** On screen: the first camera frame, the notice, the video start (`duration` starts). */
  playing?: number;
  /** The media library video ended. */
  ended?: number;
  /** The viewer pressed Back and Samstream closes. */
  closed?: number;
  /** With `playing`: the input shown in the corner ("TV1", "HDMI2"). */
  source?: string;
}

/** Ask HA for settings and any command newer than `since`. */
export async function fetchSession(
  fetchText: Fetch,
  config: PackageConfig,
  since: number,
  report: SessionReport = {},
): Promise<{ settings: Partial<TvSettings>; session: Session }> {
  const extra = (Object.keys(report) as (keyof SessionReport)[])
    .filter((key) => report[key] !== undefined)
    .map((key) => `&${key}=${report[key]}`)
    .join("");
  const url = sessionUrl(config, since) + extra;
  const raw = JSON.parse(await fetchText(url, HA_TIMEOUT_MS)) as {
    settings?: unknown;
    seq?: unknown;
    command?: unknown;
  };
  return {
    settings: normalizeSettings(raw.settings),
    session: { seq: typeof raw.seq === "number" ? raw.seq : since, command: raw.command ?? null },
  };
}

export async function loadSettings(
  fetchText: Fetch,
  store: SettingsStore | undefined,
): Promise<LoadedSettings> {
  const config = await fetchText("samstream.json", HA_TIMEOUT_MS).then(parseConfig, () => undefined);
  const base = { ...DEFAULT_SETTINGS, ...config?.settings };
  if (config?.ha_url && config.tv_secret) {
    try {
      const { settings: remote, session } = await fetchSession(fetchText, config, 0);
      try {
        store?.setItem(CACHE_KEY, JSON.stringify(remote));
      } catch {
        // Storage unavailable: still use the answer this time.
      }
      return { settings: { ...base, ...remote }, config, source: "home-assistant", session };
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
