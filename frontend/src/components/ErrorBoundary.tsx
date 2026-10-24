import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

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
    return (
      <div style={{
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        minHeight: "100vh", gap: "16px", padding: "24px", fontFamily: "system-ui, sans-serif",
        color: "var(--ink-900, #2a2a2a)", background: "var(--ivory-100, #f5f1e7)",
      }}>
        <h1 style={{ fontSize: "24px", margin: 0 }}>Something went wrong</h1>
        <p style={{ margin: 0, color: "var(--ink-500, #777)" }}>
          An unexpected error occurred. Please reload the page.
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
          Reload
        </button>
      </div>
    );
  }
}
