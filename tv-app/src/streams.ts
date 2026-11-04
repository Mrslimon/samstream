/** Camera streams the app can play, and helpers for showing them safely. */

import type { Corner } from "./pip";

export interface CameraStream {
  label: string;
  url: string;
  /** "avplay" (default) for HLS/HTTP URLs, "mse" for go2rtc ws://…/api/ws?src= URLs. */
  type?: "avplay" | "mse";
  lowLatency?: boolean;
  /** MSE only: also ask go2rtc for audio (this TV cannot decode FLAC; needs AAC). */
  audio?: boolean;
  /** Keep the TV's own picture (Live TV / HDMI) in this corner. */
  tvCorner?: Corner;
  /** Corner mode: the same camera as a picture stream (no video layer). */
  mjpegUrl?: string;
}

/** Keep only well-formed entries (anything else dropped, not the whole list). */
export function parseCameraList(raw: unknown): CameraStream[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.filter(
    (item): item is CameraStream =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as CameraStream).label === "string" &&
      typeof (item as CameraStream).url === "string",
  );
}

/**
 * Development streams from VITE_SPIKE_STREAMS (a JSON array of {label, url, type?});
 * anything malformed is dropped. Bundled builds have none: Home Assistant sends
 * the configured camera list (milestone 8, Configure → Cameras) and ad-hoc
 * `play_stream` calls send one more at launch.
 */
export function parseStreams(raw: string | undefined): CameraStream[] {
  if (!raw) {
    return [];
  }
  try {
    return parseCameraList(JSON.parse(raw));
  } catch {
    return [];
  }
}

/** Hide credentials before showing a URL on screen. */
export function redactUrl(url: string): string {
  return url.replace(/\/\/[^/@]*@/, "//***@");
}
