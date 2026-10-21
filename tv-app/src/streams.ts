/** Camera streams the app can play, and helpers for showing them safely. */

export interface CameraStream {
  label: string;
  url: string;
  /** "avplay" (default) for HLS/HTTP URLs, "mse" for go2rtc ws://…/api/ws?src= URLs. */
  type?: "avplay" | "mse";
  lowLatency?: boolean;
  /** MSE only: also ask go2rtc for audio (this TV cannot decode FLAC; needs AAC). */
  audio?: boolean;
}

/**
 * Development streams from VITE_SPIKE_STREAMS (a JSON array of {label, url, type?});
 * anything malformed is dropped. Bundled builds have none: Home Assistant sends
 * the stream at launch from milestone 8.
 */
export function parseStreams(raw: string | undefined): CameraStream[] {
  if (!raw) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(
      (item): item is CameraStream =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as CameraStream).label === "string" &&
        typeof (item as CameraStream).url === "string",
    );
  } catch {
    return [];
  }
}

/** Hide credentials before showing a URL on screen. */
export function redactUrl(url: string): string {
  return url.replace(/\/\/[^/@]*@/, "//***@");
}
