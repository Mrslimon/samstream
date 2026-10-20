/** Render one overlay message; dir="auto" lets the browser pick RTL for Arabic text. */
export function showOverlay(container: HTMLElement, text: string): HTMLElement {
  const message = document.createElement("p");
  message.dir = "auto";
  message.textContent = text;
  // replaceChildren() needs Chromium 86; Tizen 4.0 has 56.
  container.textContent = "";
  container.appendChild(message);
  return message;
}
