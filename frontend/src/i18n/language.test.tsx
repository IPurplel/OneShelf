import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WorkCard } from "@/components/WorkCard";
import { renderWithProviders } from "@/test/render";
import { languageName } from "./language";

describe("language labels", () => {
  it.each([['en', 'Unknown language', 'English'], ['ar', 'لغة غير معروفة', 'الإنجليزية']] as const)(
    "uses the selected %s locale, including und", (language, unknown, english) => {
      expect(languageName('und', language)).toBe(unknown);
      expect(languageName('en', language)).toBe(english);
      renderWithProviders(<WorkCard work={{ work_id: 'w1', title: 'Book', availability: { und: 1 } }} />, { language });
      expect(screen.getByText(unknown)).toBeInTheDocument();
    });
  it("preserves invalid and unsupported codes", () => {
    expect(languageName('not_a_code', 'en')).toBe('not_a_code');
    expect(languageName('zz', 'ar')).toBe('zz');
  });
});
