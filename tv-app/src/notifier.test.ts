import { afterEach, describe, expect, it, vi } from "vitest";
import { NOTIFIER_APP_ID, startNotifier } from "./notifier";

afterEach(() => {
  delete (globalThis as { tizen?: unknown }).tizen;
});

describe("startNotifier", () => {
  it("launches the notifier component with the secret as an extra", () => {
    const launchAppControl = vi.fn();
    class ApplicationControl {
      constructor(
        public operation: string,
        public uri: string | null,
        public mime: string | null,
        public category: string | null,
        public data: unknown[],
      ) {}
    }
    class ApplicationControlData {
      constructor(
        public key: string,
        public value: string[],
      ) {}
    }
    (globalThis as { tizen?: unknown }).tizen = {
      application: { launchAppControl },
      ApplicationControl,
      ApplicationControlData,
    };

    startNotifier("the-secret");

    expect(launchAppControl).toHaveBeenCalledOnce();
    const [control, appId] = launchAppControl.mock.calls[0];
    expect(appId).toBe(NOTIFIER_APP_ID);
    expect(appId).toBe("org.samstream.notifier");
    expect(control.data).toEqual([
      { key: "samstream_secret", value: ["the-secret"] },
    ]);
  });

  it("is a no-op off a real TV (no tizen)", () => {
    expect(() => startNotifier("x")).not.toThrow();
  });
});
