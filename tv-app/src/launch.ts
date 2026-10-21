/**
 * What Home Assistant sends when it opens Samstream (`samstream.play_stream`).
 *
 * HA launches the app with a DEEP_LINK whose metaTag is JSON:
 *   {"v":1,"stream":{"label":"Front door","url":"ws://ha:8123/api/samstream/…","type":"mse"},
 *    "message":"Someone is at the door"}
 * Tizen hands it over in the app control data, usually as key PAYLOAD with value
 * '{"values":"<metaTag>"}'; both that and the raw JSON are accepted.
 */

import { CORNERS, type Corner } from "./pip";
import type { CameraStream } from "./streams";

export interface LaunchPayload {
  stream: CameraStream;
  message: string;
}

export interface AppControlData {
  key: string;
  value: string[];
}

function tryJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** Accept only a WebSocket stream on the same host as HA (when HA is known). */
export function parsePayload(raw: unknown, haUrl?: string): LaunchPayload | undefined {
  if (typeof raw !== "object" || raw === null) {
    return undefined;
  }
  const { stream, message, tv_corner } = raw as {
    stream?: unknown;
    message?: unknown;
    tv_corner?: unknown;
  };
  if (typeof stream !== "object" || stream === null) {
    return undefined;
  }
  const { url, label } = stream as { url?: unknown; label?: unknown };
  if (typeof url !== "string" || !/^wss?:\/\//.test(url)) {
    return undefined;
  }
  if (haUrl && hostOf(url) !== hostOf(haUrl)) {
    return undefined;
  }
  return {
    stream: {
      label: typeof label === "string" ? label : "",
      url,
      type: "mse",
      ...(CORNERS.includes(tv_corner as Corner) ? { tvCorner: tv_corner as Corner } : {}),
    },
    message: typeof message === "string" ? message : "",
  };
}

export function payloadFromAppControl(
  data: readonly AppControlData[] | undefined,
  haUrl?: string,
): LaunchPayload | undefined {
  for (const item of data ?? []) {
    for (const value of item.value ?? []) {
      let parsed = tryJson(value);
      const wrapped = (parsed as { values?: unknown } | undefined)?.values;
      if (typeof wrapped === "string") {
        parsed = tryJson(wrapped);
      }
      const payload = parsePayload(parsed, haUrl);
      if (payload) {
        return payload;
      }
    }
  }
  return undefined;
}

/** Payload of the launch (or relaunch) request, if HA sent one. */
export function readLaunchPayload(haUrl?: string): LaunchPayload | undefined {
  try {
    const request = globalThis.tizen?.application.getCurrentApplication().getRequestedAppControl();
    return payloadFromAppControl(request?.appControl.data, haUrl);
  } catch {
    return undefined;
  }
}

function hostOf(url: string): string {
  return url.replace(/^[a-z]+:\/\//i, "").split("/")[0].toLowerCase();
}
