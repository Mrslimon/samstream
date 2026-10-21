/** D-pad focus for a horizontal row of buttons (the bottom action bar). */

export const KEY_LEFT = 37;
export const KEY_RIGHT = 39;

export class FocusRow {
  private index = 0;

  constructor(
    private readonly items: () => HTMLElement[],
    private readonly isRtl: () => boolean,
  ) {}

  /** Focus the first visible item (or the given one). */
  focus(index = 0): void {
    const items = this.visible();
    if (items.length === 0) {
      return;
    }
    this.index = Math.max(0, Math.min(index, items.length - 1));
    items[this.index].focus();
  }

  /**
   * Arrow keys move to the button that is visually next: in RTL the row is
   * mirrored, so ▶ goes to the previous item in DOM order.
   */
  move(keyCode: number): boolean {
    if (keyCode !== KEY_LEFT && keyCode !== KEY_RIGHT) {
      return false;
    }
    const forward = (keyCode === KEY_RIGHT) !== this.isRtl();
    const items = this.visible();
    if (items.length === 0) {
      return true;
    }
    const current = items.indexOf(document.activeElement as HTMLElement);
    const from = current >= 0 ? current : this.index;
    this.focus(Math.max(0, Math.min(items.length - 1, from + (forward ? 1 : -1))));
    return true;
  }

  private visible(): HTMLElement[] {
    return this.items().filter((item) => !item.hidden);
  }
}
