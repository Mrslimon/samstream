import { describe, expect, it } from "vitest";
import { parseMedia, parseNotice } from "./notice";

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
