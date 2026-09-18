/** Master §27, ledger K3: the PDF viewer must never hand a document a script engine. */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const SOURCE = readFileSync(join(process.cwd(), "src/features/reader/PdfView.tsx"), "utf8");

describe("PDF isolation", () => {
  it("never enables scripting or the annotation layer", () => {
    expect(SOURCE).not.toMatch(/enableScripting\s*:\s*true/);
    expect(SOURCE).not.toMatch(/AnnotationLayer|renderInteractiveForms/);
  });

  it("does not let the document fetch on its own", () => {
    expect(SOURCE).toMatch(/disableAutoFetch:\s*true/);
    expect(SOURCE).toMatch(/disableRange:\s*true/);
  });

  it("renders from bytes the application fetched, not from a URL the document controls", () => {
    expect(SOURCE).toMatch(/data:\s*new Uint8Array\(data\)/);
    expect(SOURCE).not.toMatch(/getDocument\(\s*(url|`|")/);
  });
});
