/**
 * Start the Samstream notifier — the .NET half of the same hybrid package.
 *
 * The notifier posts native Samsung notifications (title + text, with a chime)
 * that overlay whatever is playing — something a web app cannot do. It must be
 * RUNNING to post, and a sideloaded app cannot be started from outside the TV,
 * so the web app starts it here (it holds the `application.launch` privilege).
 *
 * We hand over this TV's secret so the notifier's LAN listener can authenticate
 * Home Assistant. This is local app-control between two apps of the same
 * package, not a network call, so it carries no signature.
 */

/** App id of the notifier package (nodisplay; started by the web app). */
export const NOTIFIER_APP_ID = "org.samstream.notifier";

const DEFAULT_OPERATION = "http://tizen.org/appcontrol/operation/default";

type Log = (message: string) => void;

/**
 * (Re)start the notifier and pass it the per-TV secret. Safe to call on every
 * boot: if it is already running the launch just re-delivers the secret. A
 * no-op off a real TV (no `tizen`).
 */
export function startNotifier(secret: string, log: Log = () => undefined): void {
  const tizen = globalThis.tizen;
  if (!tizen?.application?.launchAppControl || !tizen.ApplicationControl) {
    log("notifier: tizen app-control missing (not a Samsung TV)");
    return;
  }
  try {
    const data = tizen.ApplicationControlData
      ? [new tizen.ApplicationControlData("samstream_secret", [secret])]
      : undefined;
    const control = new tizen.ApplicationControl(
      DEFAULT_OPERATION,
      null,
      null,
      null,
      data,
    );
    tizen.application.launchAppControl(
      control,
      NOTIFIER_APP_ID,
      () => log("notifier: started"),
      (error) => log(`notifier start failed: ${error.name ?? ""} ${error.message ?? ""}`),
    );
  } catch (error) {
    log(`notifier: ${String(error)}`);
  }
}
