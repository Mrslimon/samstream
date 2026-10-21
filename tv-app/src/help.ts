/** Remote control cheat sheet card, in the UI language. */

export function renderHelp(
  container: HTMLElement,
  title: string,
  lines: readonly string[],
): void {
  container.textContent = "";
  const heading = document.createElement("h2");
  heading.textContent = title;
  container.appendChild(heading);
  for (const line of lines) {
    const row = document.createElement("p");
    // Key names are Latin; let each line pick its own direction.
    row.dir = "auto";
    row.textContent = line;
    container.appendChild(row);
  }
}
