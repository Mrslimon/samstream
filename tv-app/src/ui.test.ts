import { describe, expect, it } from "vitest";
import { FocusRow, KEY_LEFT, KEY_RIGHT } from "./focus";
import { renderHelp } from "./help";
import { applyLanguage, detectLanguage, strings } from "./i18n";

describe("language", () => {
  it("picks Arabic for any ar locale and English otherwise", () => {
    expect(detectLanguage("ar_AE")).toBe("ar");
    expect(detectLanguage("ar-EG")).toBe("ar");
    expect(detectLanguage("en-US")).toBe("en");
    expect(detectLanguage(undefined)).toBe("en");
  });

  it("sets lang and dir so logical CSS flips", () => {
    const root = document.createElement("html");
    applyLanguage(root, "ar");
    expect([root.lang, root.dir]).toEqual(["ar", "rtl"]);
    applyLanguage(root, "en");
    expect([root.lang, root.dir]).toEqual(["en", "ltr"]);
  });

  it("has the same keys in both languages", () => {
    expect(Object.keys(strings("ar")).sort()).toEqual(Object.keys(strings("en")).sort());
    expect(strings("ar").helpPlayer).toHaveLength(strings("en").helpPlayer.length);
  });
});

function row(rtl: boolean): { focus: FocusRow; buttons: HTMLButtonElement[] } {
  document.body.innerHTML = "";
  const buttons = ["play", "help", "exit"].map((id) => {
    const button = document.createElement("button");
    button.id = id;
    document.body.appendChild(button);
    return button;
  });
  return { focus: new FocusRow(() => buttons, () => rtl), buttons };
}

describe("FocusRow", () => {
  it("moves with the arrows and stops at the ends (LTR)", () => {
    const { focus, buttons } = row(false);
    focus.focus();
    expect(document.activeElement).toBe(buttons[0]);
    focus.move(KEY_RIGHT);
    expect(document.activeElement).toBe(buttons[1]);
    focus.move(KEY_RIGHT);
    focus.move(KEY_RIGHT);
    expect(document.activeElement).toBe(buttons[2]);
    focus.move(KEY_LEFT);
    expect(document.activeElement).toBe(buttons[1]);
  });

  it("mirrors the arrows in RTL", () => {
    const { focus, buttons } = row(true);
    focus.focus();
    focus.move(KEY_LEFT);
    expect(document.activeElement).toBe(buttons[1]);
    focus.move(KEY_RIGHT);
    expect(document.activeElement).toBe(buttons[0]);
  });

  it("skips hidden buttons and ignores other keys", () => {
    const { focus, buttons } = row(false);
    buttons[0].hidden = true;
    focus.focus();
    expect(document.activeElement).toBe(buttons[1]);
    expect(focus.move(13)).toBe(false);
  });
});

describe("renderHelp", () => {
  it("renders a title and one line per key", () => {
    const container = document.createElement("aside");
    renderHelp(container, "Remote control", strings("en").helpHome);
    expect(container.querySelector("h2")?.textContent).toBe("Remote control");
    expect(container.querySelectorAll("p")).toHaveLength(strings("en").helpHome.length);
  });
});
