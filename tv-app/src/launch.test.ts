import { describe, expect, it } from "vitest";
import { parseOpen, parsePayload, payloadFromAppControl } from "./launch";

const HA = "http://192.168.1.5:8123";
const PAYLOAD = {
  v: 1,
  stream: { label: "Front door", url: "ws://192.168.1.5:8123/api/samstream/tv/s/stream/x", type: "mse" },
  message: "شخص عند الباب",
};

describe("parsePayload", () => {
  it("reads a stream on HA's host", () => {
    expect(parsePayload(PAYLOAD, HA)).toEqual({
      stream: { label: "Front door", url: PAYLOAD.stream.url, type: "mse" },
      message: "شخص عند الباب",
    });
  });

  it("refuses other hosts and non-WebSocket URLs", () => {
    const elsewhere = { stream: { url: "ws://10.0.0.9:8123/x" } };
    expect(parsePayload(elsewhere, HA)).toBeUndefined();
    expect(parsePayload({ stream: { url: "rtsp://192.168.1.5/x" } }, HA)).toBeUndefined();
    expect(parsePayload({ stream: "nope" }, HA)).toBeUndefined();
    expect(parsePayload(null, HA)).toBeUndefined();
  });

  it("accepts any host when HA is unknown (development build)", () => {
    expect(parsePayload({ stream: { url: "ws://10.0.0.9:1984/api/ws?src=a" } })?.message).toBe("");
  });
});

describe("payloadFromAppControl", () => {
  it("unwraps Samsung's PAYLOAD {values: ...} wrapper", () => {
    const data = [{ key: "PAYLOAD", value: [JSON.stringify({ values: JSON.stringify(PAYLOAD) })] }];
    expect(payloadFromAppControl(data, HA)?.stream.label).toBe("Front door");
  });

  it("accepts raw JSON and skips unrelated keys", () => {
    const data = [
      { key: "callerAppId", value: ["org.tizen.home"] },
      { key: "metaTag", value: [JSON.stringify(PAYLOAD)] },
    ];
    expect(payloadFromAppControl(data, HA)?.message).toBe("شخص عند الباب");
  });

  it("returns nothing for a plain launch", () => {
    expect(payloadFromAppControl([], HA)).toBeUndefined();
    expect(payloadFromAppControl(undefined, HA)).toBeUndefined();
  });
});

describe("parseOpen", () => {
  it("reads a YouTube video id", () => {
    expect(parseOpen({ youtube: "dQw4w9WgXcQ" })).toEqual({ youtube: "dQw4w9WgXcQ" });
  });

  it("reads a web URL", () => {
    expect(parseOpen({ url: "https://example.com" })).toEqual({ url: "https://example.com" });
  });

  it("rejects bad ids, non-http URLs and junk", () => {
    expect(parseOpen({ youtube: "short" })).toBeUndefined();
    expect(parseOpen({ url: "ftp://example.com" })).toBeUndefined();
    expect(parseOpen({ url: "javascript:alert(1)" })).toBeUndefined();
    expect(parseOpen(null)).toBeUndefined();
    expect(parseOpen({})).toBeUndefined();
  });
});
