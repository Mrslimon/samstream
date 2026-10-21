import { describe, expect, it } from "vitest";
import { parseVideoInfo } from "./player";
import { parseStreams, redactUrl } from "./streams";

describe("parseStreams", () => {
  it("keeps well-formed entries only", () => {
    const raw = JSON.stringify([{ label: "a", url: "rtsp://x" }, { label: 1 }, "junk"]);
    expect(parseStreams(raw)).toEqual([{ label: "a", url: "rtsp://x" }]);
  });

  it("returns nothing for missing or invalid JSON", () => {
    expect(parseStreams(undefined)).toEqual([]);
    expect(parseStreams("{nope")).toEqual([]);
  });
});

describe("redactUrl", () => {
  it("hides user and password", () => {
    expect(redactUrl("rtsp://user:pass@10.0.0.2:554/s")).toBe("rtsp://***@10.0.0.2:554/s");
    expect(redactUrl("http://10.0.0.2/s")).toBe("http://10.0.0.2/s");
  });
});

describe("parseVideoInfo", () => {
  it("reads codec and resolution from the VIDEO stream", () => {
    const info = parseVideoInfo([
      { index: 0, type: "AUDIO", extra_info: "{}" },
      { index: 1, type: "VIDEO", extra_info: '{"fourCC":"H264","Width":"2560","Height":"1440"}' },
    ]);
    expect(info).toEqual({ codec: "H264", width: 2560, height: 1440 });
  });
});
