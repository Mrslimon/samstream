/** Render one overlay message; dir="auto" lets the browser pick RTL for Arabic text. */
export function showOverlay(container: HTMLElement, text: string): HTMLElement {
  const message = document.createElement("p");
  message.dir = "auto";
  const inner = document.createElement("span");
  inner.textContent = text;
  message.appendChild(inner);
  // replaceChildren() needs Chromium 86; Tizen 4.0 has 56.
  container.textContent = "";
  container.appendChild(message);
  return message;
}

// Reading pace for text taller than the card, and pauses at both ends.
const SCROLL_PX_PER_SECOND = 30;
const SCROLL_HOLD_SECONDS = 3;

/**
 * Text taller than the card (CSS caps its height) scrolls up slowly, holds,
 * and scrolls back, so a long message can be read in full.
 */
export function scrollWhenLong(card: HTMLElement): void {
  const inner = card.firstElementChild as HTMLElement | null;
  if (!inner || typeof inner.animate !== "function") return;
  // Measure once the card is laid out.
  requestAnimationFrame(() => {
    const style = getComputedStyle(card);
    const room =
      card.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    const distance = Math.ceil(inner.offsetHeight - room);
    if (!(distance > 0)) return;
    card.classList.add("scrolling");
    const travel = distance / SCROLL_PX_PER_SECOND;
    const total = travel + 2 * SCROLL_HOLD_SECONDS;
    const hold = SCROLL_HOLD_SECONDS / total;
    const end = `translateY(${-distance}px)`;
    inner.animate(
      [
        { transform: "translateY(0)", offset: 0 },
        { transform: "translateY(0)", offset: hold },
        { transform: end, offset: 1 - hold },
        { transform: end, offset: 1 },
      ],
      { duration: total * 1000, iterations: Infinity, direction: "alternate", easing: "linear" },
    );
  });
}
