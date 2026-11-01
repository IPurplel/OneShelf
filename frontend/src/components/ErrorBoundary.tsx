import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { STRINGS } from "@/i18n/strings";

type Props = { children: ReactNode };
type State = { error: Error | null };

function getBoundaryStrings() {
  const lang = (typeof localStorage !== "undefined" && localStorage.getItem("oneshelf.language")) || "en";
  const table = lang === "ar" ? STRINGS.ar : STRINGS.en;
  return {
    title: table["error.boundary.title"] ?? "Something went wrong",
    body: table["error.boundary.body"] ?? "An unexpected error occurred. Please reload the page.",
    reload: table["error.boundary.reload"] ?? "Reload",
    dir: lang === "ar" ? "rtl" as const : "ltr" as const,
  };
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Uncaught rendering error:", error, info.componentStack);
  }

  render() {
    if (this.state.error === null) return this.props.children;
    const s = getBoundaryStrings();
    return (
      <div dir={s.dir} style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        minHeight: "100vh", gap: "16px", padding: "24px", fontFamily: "system-ui, sans-serif",
        color: "var(--ink-900, #2a2a2a)", background: "var(--ivory-100, #f5f1e7)",
      }}>
        <h1 style={{ fontSize: "24px", margin: 0 }}>{s.title}</h1>
        <p style={{ margin: 0, color: "var(--ink-500, #777)" }}>
          {s.body}
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{
            padding: "10px 24px", fontSize: "16px", cursor: "pointer",
            border: "1px solid var(--surface-border, #ccc)", borderRadius: "8px",
            background: "var(--paper, #fff)", color: "inherit",
          }}
        >
          {s.reload}
        </button>
      </div>
    );
  }
}
