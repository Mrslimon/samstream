/**
 * Commands from Home Assistant besides cameras:
 *   {"action":"notice","title":"…","message":"…","severity":"alert","sound":"http://…"}
 *     (severity info, warning, alert or success: a check that draws itself)
 *     (`samstream.show_message`): a full-screen message, optionally with a sound;
 *   {"action":"media","title":"…","url":"http://…","kind":"video"}
 *     (`media_player.play_media` with an item from HA's media library).
 * URLs are signed by HA; only http(s) is accepted.
 */

export type Severity = "info" | "warning" | "alert" | "success";

export interface Notice {
  title: string;
  message: string;
  severity: Severity;
  sound: string | undefined;
}

export interface MediaItem {
  title: string;
  url: string;
  kind: "video" | "audio";
}

const SEVERITIES: readonly Severity[] = ["info", "warning", "alert", "success"];

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function httpUrl(value: unknown): string | undefined {
  return typeof value === "string" && /^https?:\/\//.test(value) ? value : undefined;
}

export function parseNotice(raw: unknown): Notice | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const { title, message, severity, sound } = raw as Record<string, unknown>;
  if (!text(title) && !text(message)) return undefined;
  return {
    title: text(title),
    message: text(message),
    severity: SEVERITIES.includes(severity as Severity) ? (severity as Severity) : "info",
    sound: httpUrl(sound),
  };
}

export function parseMedia(raw: unknown): MediaItem | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const { title, url, kind } = raw as Record<string, unknown>;
  const href = httpUrl(url);
  if (!href) return undefined;
  return { title: text(title), url: href, kind: kind === "audio" ? "audio" : "video" };
}
