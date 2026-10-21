// Minimal typings for the Samsung Product API / Tizen Web API parts Samstream uses.
// Both globals are injected by the TV runtime and are absent in a desktop browser.

export type AVPlayState = "NONE" | "IDLE" | "READY" | "PLAYING" | "PAUSED";

export interface AVPlayListener {
  onbufferingstart?: () => void;
  onbufferingprogress?: (percent: number) => void;
  onbufferingcomplete?: () => void;
  oncurrentplaytime?: (ms: number) => void;
  onstreamcompleted?: () => void;
  onevent?: (eventType: string, eventData: string) => void;
  onerror?: (eventType: string) => void;
}

export interface AVPlayStreamInfo {
  index: number;
  type: "VIDEO" | "AUDIO" | "TEXT";
  extra_info: string;
}

export interface AVPlay {
  open(url: string): void;
  close(): void;
  prepareAsync(onSuccess: () => void, onError: (error: unknown) => void): void;
  play(): void;
  stop(): void;
  pause(): void;
  suspend(): void;
  restore(): void;
  getState(): AVPlayState;
  setListener(listener: AVPlayListener): void;
  setDisplayRect(x: number, y: number, width: number, height: number): void;
  setDisplayMethod(mode: string): void;
  setBufferingParam(option: string, unit: string, amount: number): void;
  setTimeoutForBuffering(seconds: number): void;
  getCurrentStreamInfo(): AVPlayStreamInfo[];
}

declare global {
  // eslint-disable-next-line no-var
  var webapis: { avplay: AVPlay } | undefined;
  // eslint-disable-next-line no-var
  var tizen:
    | {
        tvinputdevice: { registerKey(keyName: string): void };
        tvwindow?: {
          show(
            success: (rect: string[], type: string) => void,
            error: (error: { name: string; message: string }) => void,
            rect: string[],
            type: "MAIN",
          ): void;
          hide(success: () => void, error: () => void, type: "MAIN"): void;
        };
        application: {
          getCurrentApplication(): {
            exit(): void;
            getRequestedAppControl(): {
              appControl: { data: { key: string; value: string[] }[] };
            } | null;
          };
        };
      }
    | undefined;
}
