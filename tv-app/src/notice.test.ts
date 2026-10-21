import { describe, expect, it } from "vitest";
import { parsePayload } from "./launch";
import { parseMedia, parseNotice } from "./notice";
import { cornerRect, holeClipPath } from "./pip";

describe("parseNotice", () => {
  it("reads title, message, severity and sound", () => {
    expect(
      parseNotice({
        action: "notice",
        title: "الباب الأمامي",
        message: "شخص عند الباب",
        severity: "alert",
        sound: "http://192.168.1.5:8123/api/tts_proxy/x.mp3",
      }),
    ).toEqual({
      title: "الباب الأمامي",
      message: "شخص عند الباب",
      severity: "alert",
      sound: "http://192.168.1.5:8123/api/tts_proxy/x.mp3",
    });
  });

  it("defaults the severity and drops non-http sounds", () => {
    expect(parseNotice({ message: "Hi", severity: "loud", sound: "file:///etc/x" })).toEqual({
      title: "",
      message: "Hi",
      severity: "info",
      sound: undefined,
    });
  });

  it("needs a title or a message", () => {
    expect(parseNotice({ severity: "info" })).toBeUndefined();
    expect(parseNotice(null)).toBeUndefined();
  });
});

describe("parseMedia", () => {
  it("accepts http(s) files", () => {
    expect(parseMedia({ title: "Clip", url: "https://ha.local/media/a.mp4", kind: "video" })).toEqual({
      title: "Clip",
      url: "https://ha.local/media/a.mp4",
      kind: "video",
    });
    expect(parseMedia({ url: "http://ha/a.mp3", kind: "audio" })?.kind).toBe("audio");
  });

  it("rejects other URLs", () => {
    expect(parseMedia({ url: "javascript:alert(1)" })).toBeUndefined();
    expect(parseMedia({ title: "x" })).toBeUndefined();
  });
});

describe("TV picture in a corner", () => {
  it("places the window in each corner with a margin", () => {
    expect(cornerRect("top_right")).toEqual({ left: 1216, top: 64, width: 640, height: 360 });
    expect(cornerRect("bottom_left")).toEqual({ left: 64, top: 656, width: 640, height: 360 });
  });

  it("cuts the window out of the camera video", () => {
    expect(holeClipPath(cornerRect("top_left"))).toBe(
      "polygon(evenodd, 0 0, 100% 0, 100% 100%, 0 100%, 0 0, " +
        "64px 64px, 64px 424px, 704px 424px, 704px 64px, 64px 64px)",
    );
  });

  it("reads the corner from Home Assistant's play command", () => {
    const stream = { label: "Door", url: "ws://192.168.1.5:8123/x" };
    expect(parsePayload({ stream, tv_corner: "bottom_right" })?.stream.tvCorner).toBe("bottom_right");
    expect(parsePayload({ stream, tv_corner: null })?.stream.tvCorner).toBeUndefined();
    expect(parsePayload({ stream, tv_corner: "middle" })?.stream.tvCorner).toBeUndefined();
  });
});
