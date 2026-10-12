export const CATEGORIES = [
  "Manga", "Webtoons", "Comics", "Books", "Children's books", "Academic books", "Textbooks",
  "Poetry", "Religious texts", "Journal", "Papers", "Reports", "Manuscripts", "Newspapers", "Digital library",
] as const;

const CATEGORY_ALIASES: Record<string, string> = {
  manga: "Manga", مانجا: "Manga", webtoon: "Webtoons", webtoons: "Webtoons",
  comics: "Comics", comic: "Comics", books: "Books", book: "Books", كتب: "Books",
  children: "Children's books", "children's": "Children's books", kids: "Children's books",
  academic: "Academic books", "academic:books": "Academic books", textbooks: "Textbooks",
  poetry: "Poetry", religion: "Religious texts", journal: "Journal", journals: "Journal", مجلة: "Journal",
  papers: "Papers", reports: "Reports", manuscripts: "Manuscripts", مخطوطات: "Manuscripts",
  newspapers: "Newspapers", library: "Digital library",
};

const ARABIC_CATEGORIES: Record<string, string> = {
  Manga: "مانجا", Webtoons: "ويب تون", Comics: "قصص مصورة", Books: "كتب",
  "Children's books": "كتب الأطفال", "Academic books": "كتب أكاديمية", Textbooks: "كتب دراسية",
  Poetry: "شعر", "Religious texts": "نصوص دينية", Journal: "مجلة", Papers: "أبحاث",
  Reports: "تقارير", Manuscripts: "مخطوطات", Newspapers: "صحف", "Digital library": "مكتبة رقمية",
};

export function categoryLabel(category: string, language: "en" | "ar"): string {
  return language === "ar" ? ARABIC_CATEGORIES[category] ?? category : category;
}

export function languageLabel(code: string, language: "en" | "ar"): string {
  const normalized = code.toUpperCase();
  const known: Record<string, [string, string]> = {
    AR: ["Arabic", "العربية"], EN: ["English", "الإنجليزية"], FA: ["Persian", "الفارسية"],
    JA: ["Japanese", "اليابانية"], MULTI: ["Multilingual", "متعددة اللغات"],
  };
  return known[normalized]?.[language === "ar" ? 1 : 0] ?? normalized;
}

export function parseScopes(input: string): { query: string; categories: string[]; languages: string[] } {
  const categories: string[] = [];
  const languages: string[] = [];
  const words: string[] = [];
  for (const word of input.trim().match(/(?:[^\s"]*"[^"]*"|\S+)/g) ?? []) {
    const lower = word.toLocaleLowerCase();
    const categoryTerm = lower.startsWith("category:") ? lower.slice(9).replace(/^"|"$/g, "") : lower;
    const category = CATEGORY_ALIASES[categoryTerm] ?? CATEGORIES.find(value => value.toLocaleLowerCase() === categoryTerm);
    if (category && (lower.startsWith("category:") || ["مانجا", "كتب", "مجلة", "مخطوطات", "academic", "children", "academic:books"].includes(lower))) {
      if (!categories.includes(category)) categories.push(category);
      continue;
    }
    const langMatch = lower.match(/^(?:lang|language):([\p{L}-]+)$/u);
    if (langMatch) {
      const term = langMatch[1]!;
      const code = term === "arabic" || term === "العربية" ? "AR" : term.toUpperCase();
      if (!languages.includes(code)) languages.push(code);
      continue;
    }
    words.push(word);
  }
  return { query: words.join(" "), categories, languages };
}
