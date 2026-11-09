import { directionFromText } from "@/features/reader/epub";

/** The colours of a highlight, as the quote card shows them, for the image's rule beside the text. */
const RULE: Record<string, string> = { yellow: "#d9bf86", green: "#8fb878", blue: "#7fa7c9", pink: "#d99aa8" };
const SIZE = 1080;
const MARGIN = 120;

function wrap(context: CanvasRenderingContext2D, text: string, width: number): string[] {
  const lines: string[] = [];
  for (const paragraph of text.split(/\n+/)) {
    let line = "";
    for (const word of paragraph.split(/\s+/)) {
      const candidate = line ? `${line} ${word}` : word;
      if (line && context.measureText(candidate).width > width) {
        lines.push(line);
        line = word;
      } else {
        line = candidate;
      }
    }
    if (line) lines.push(line);
  }
  return lines;
}

/**
 * A square image of one quote, to share: the sentence large on ivory paper, its book beneath, OneShelf's name
 * small at the foot. Drawn on this device and saved by the browser; nothing is sent anywhere.
 */
export async function shareQuoteImage(quote: { text: string; work_title: string; colour: string }, brand: string) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const context = canvas.getContext("2d");
  if (context === null) throw new Error("no canvas");
  const rtl = directionFromText(quote.text) === "rtl";
  context.direction = rtl ? "rtl" : "ltr";
  context.textAlign = "start";
  context.fillStyle = "#f3eee5";
  context.fillRect(0, 0, SIZE, SIZE);
  context.fillStyle = RULE[quote.colour] ?? RULE.yellow!;
  context.fillRect(rtl ? SIZE - MARGIN + 24 : MARGIN - 32, MARGIN, 8, SIZE - MARGIN * 2 - 120);

  let size = 56;
  let lines: string[] = [];
  do {
    context.font = `${size}px "Noto Naskh Arabic", "Noto Serif", Georgia, serif`;
    lines = wrap(context, quote.text, SIZE - MARGIN * 2);
    size -= 4;
  } while (lines.length * size * 1.6 > SIZE - MARGIN * 2 - 160 && size > 24);
  const x = rtl ? SIZE - MARGIN : MARGIN;
  context.fillStyle = "#1c1b18";
  lines.forEach((line, index) => context.fillText(line, x, MARGIN + size + index * size * 1.6));

  context.font = `32px "Noto Naskh Arabic", "Noto Serif", Georgia, serif`;
  context.fillStyle = "#4c6b3c";
  context.fillText(`— ${quote.work_title}`, x, SIZE - MARGIN - 40);
  context.font = `24px "Noto Naskh Arabic", "Noto Serif", Georgia, serif`;
  context.fillStyle = "#8a6a43";
  context.fillText(brand, x, SIZE - MARGIN + 10);

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (blob === null) throw new Error("no image");
  const file = new File([blob], "quote.png", { type: "image/png" });
  // A phone shares it straight to an app; elsewhere it is saved as a file.
  if (typeof navigator.canShare === "function" && navigator.canShare({ files: [file] })) {
    await navigator.share({ files: [file] });
    return;
  }
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: "quote.png" });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
