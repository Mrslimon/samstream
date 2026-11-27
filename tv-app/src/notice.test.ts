import { describe, expect, it } from "vitest";
import { parsePayload } from "./launch";
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

  it("accepts the success severity", () => {
    expect(parseNotice({ title: "Done", severity: "success" })?.severity).toBe("success");
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

describe("text over the camera", () => {
  const stream = { label: "Door", url: "ws://192.168.1.5:8123/x" };

  it("reads its position and size from Home Assistant's play command", () => {
    const payload = parsePayload({ stream, text_position: "top", text_size: "extra_large" });
    expect(payload?.textPosition).toBe("top");
    expect(payload?.textSize).toBe("extra_large");
    // The app saves the parsed payload and reads it again after a restart.
    expect(parsePayload(JSON.parse(JSON.stringify(payload)))).toEqual(payload);
  });

  it("ignores values it does not know", () => {
    const payload = parsePayload({ stream, text_position: "left", text_size: 3 });
    expect(payload?.textPosition).toBeUndefined();
    expect(payload?.textSize).toBeUndefined();
  });
});
