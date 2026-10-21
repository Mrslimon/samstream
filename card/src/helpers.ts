/** The parts of Home Assistant's `hass` object the card uses. */
export interface HassEntity {
  entity_id: string;
  state: string;
  attributes: Record<string, unknown>;
}

export interface HassEntityRegistryEntry {
  entity_id: string;
  device_id?: string | null;
  platform?: string;
}

export interface Hass {
  states: Record<string, HassEntity>;
  entities?: Record<string, HassEntityRegistryEntry>;
  language?: string;
  locale?: { language: string };
  callService(domain: string, service: string, data: Record<string, unknown>): Promise<unknown>;
  callWS<T>(message: Record<string, unknown>): Promise<T>;
}

export interface TvApp {
  id: string;
  name: string;
  logo: string | null;
}

export interface AppsAnswer {
  home: string;
  current: string | null;
  apps: TvApp[];
}

/** The remote entity on the same device as the media player (for key presses). */
export function remoteEntity(hass: Hass, mediaPlayer: string): string | undefined {
  const device = hass.entities?.[mediaPlayer]?.device_id;
  if (device) {
    for (const entry of Object.values(hass.entities ?? {})) {
      if (entry.device_id === device && entry.entity_id.startsWith("remote.")) {
        return entry.entity_id;
      }
    }
  }
  // Same object ID is the integration's naming (media_player.x / remote.x).
  const guess = `remote.${mediaPlayer.split(".", 2)[1]}`;
  return hass.states[guess] ? guess : undefined;
}

/** Cameras to offer: the configured ones, else every camera in HA. */
export function cameraList(hass: Hass, configured: string[] | undefined): string[] {
  if (configured && configured.length > 0) return configured.filter((id) => hass.states[id]);
  return Object.keys(hass.states)
    .filter((id) => id.startsWith("camera."))
    .sort((a, b) => friendlyName(hass, a).localeCompare(friendlyName(hass, b)));
}

export function friendlyName(hass: Hass, entityId: string): string {
  const name = hass.states[entityId]?.attributes.friendly_name;
  return typeof name === "string" && name ? name : entityId;
}

/** First letter (or two for Latin words), for apps without a logo. */
export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = Array.from(words[0])[0] ?? "?";
  const latin = /^[A-Za-z0-9]/.test(first);
  const second = latin && words.length > 1 ? (Array.from(words[1])[0] ?? "") : "";
  return (first + second).toUpperCase();
}

/** A stable, pleasant colour per app name (hue from a string hash). */
export function tileColor(name: string): string {
  let hash = 0;
  for (const char of name) hash = (hash * 31 + (char.codePointAt(0) ?? 0)) | 0;
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 55% 46%)`;
}

export const SECTIONS = ["tv", "cameras", "message", "apps", "remote", "media"] as const;
export type Section = (typeof SECTIONS)[number];

export interface SectionConfig {
  sections?: string[];
  show_cameras?: boolean;
  show_message?: boolean;
  show_apps?: boolean;
  show_remote?: boolean;
}

/** Sections to draw, in order; cards from before `sections` keep their switches. */
export function sectionsOf(config: SectionConfig): Section[] {
  if (Array.isArray(config.sections)) {
    const known = config.sections.filter((s): s is Section => (SECTIONS as readonly string[]).includes(s));
    return known.filter((s, i) => known.indexOf(s) === i);
  }
  const shown: Section[] = ["tv"];
  if (config.show_cameras !== false) shown.push("cameras");
  if (config.show_message !== false) shown.push("message");
  if (config.show_apps !== false) shown.push("apps");
  if (config.show_remote !== false) shown.push("remote", "media");
  return shown;
}
