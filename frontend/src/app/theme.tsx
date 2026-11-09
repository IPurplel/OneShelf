import { createContext, useContext, useEffect, useLayoutEffect, useState } from "react";
import type { ReactNode } from "react";

export type ThemeChoice = "system" | "light" | "dark";

const STORAGE_KEY = "oneshelf.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
const ThemeContext = createContext<{ theme: ThemeChoice; setTheme: (theme: ThemeChoice) => void } | null>(null);

function storedTheme(): ThemeChoice {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system";
  }
}

// The browser's own bar (phones, installed apps) takes the page's canvas colour (--ivory-100 in tokens.css).
const THEME_COLOR = { light: "#f3eee5", dark: "#111b15" } as const;

function applyResolved(resolved: "light" | "dark"): void {
  document.documentElement.dataset.resolvedTheme = resolved;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[resolved]);
}

function resolveTheme(theme: ThemeChoice): "light" | "dark" {
  if (theme !== "system") return theme;
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeChoice>(storedTheme);

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme;
    applyResolved(resolveTheme(theme));
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // The interface remains usable when storage is blocked.
    }
  }, [theme]);

  useEffect(() => {
    if (theme !== "system" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(DARK_QUERY);
    const update = () => applyResolved(media.matches ? "dark" : "light");
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [theme]);

  return <ThemeContext.Provider value={{ theme, setTheme }}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used inside ThemeProvider");
  return context;
}
