import { useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/api/client";
import { useI18n } from "@/i18n/i18n";

/** The window OneShelf opens is a real browser at this size; clicks are relayed in its own pixels. */
const VIEW = { width: 1280, height: 800 };

const KEYS = new Set(["Enter", "Tab", "Backspace", "Delete", "Escape",
                      "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"]);

type Login = { login_id: string; status: string };
type Completion = { outcome: "connected" | "not_logged_in"; status: string };

/**
 * Use My Session (Master §13, §32.12).
 *
 * OneShelf opens a real browser window on the server and relays it: you see the page, your clicks and
 * keystrokes go straight to it, and nothing you type is stored or written to the log. When you say you
 * are signed in, the session — not your password — is captured, scoped to that source's own domains, and
 * kept encrypted. Nothing is captured if you cancel.
 */
export function LoginSession({ sourceId, sourceName, onClose }: {
  sourceId: string; sourceName: string; onClose: () => void;
}) {
  const { t } = useI18n();
  const [login, setLogin] = useState<Login | null>(null);
  const [tick, setTick] = useState(0);
  const [outcome, setOutcome] = useState<Completion | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const frame = useRef<HTMLImageElement | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current); }, []);

  const say = (error: unknown) =>
    setProblem(error instanceof ApiError ? error.message : t("state.offline"));

  const open = async () => {
    setProblem(null);
    setBusy(true);
    try {
      setLogin(await api.post<Login>(`/api/sources/${sourceId}/login`));
    } catch (error) {
      say(error);
    } finally {
      setBusy(false);
    }
  };

  /** Relayed input is fire-and-forget: the next frame shows what happened. */
  const send = (body: Record<string, string | number>) => {
    if (login === null) return;
    api.post(`/api/logins/${login.login_id}/input`, body)
      .then(() => setTick((n) => n + 1))
      .catch(say);
  };

  const onClick = (event: React.MouseEvent<HTMLImageElement>) => {
    const box = frame.current?.getBoundingClientRect();
    const across = box && box.width > 0 ? (event.clientX - box.left) / box.width : 0;
    const down = box && box.height > 0 ? (event.clientY - box.top) / box.height : 0;
    send({ type: "click", x: Math.round(across * VIEW.width), y: Math.round(down * VIEW.height) });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLImageElement>) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key.length === 1) {
      event.preventDefault();
      send({ type: "type", text: event.key });        // relayed as typed; never kept by OneShelf
    } else if (KEYS.has(event.key)) {
      event.preventDefault();
      send({ type: "key", key: event.key });
    }
  };

  const complete = async () => {
    if (login === null) return;
    setProblem(null);
    setBusy(true);
    try {
      setOutcome(await api.post<Completion>(`/api/logins/${login.login_id}/complete`));
    } catch (error) {
      say(error);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    try {
      if (login !== null) await api.delete(`/api/logins/${login.login_id}`);
    } catch {
      // A window that has already closed is not a problem worth reporting.
    } finally {
      onClose();
    }
  };

  const connected = outcome?.outcome === "connected";

  return (
    <div className="confirm confirm--wide" role="dialog" aria-modal="true" aria-label={t("login.title")}>
      <h2 className="display">{t("login.title", { name: sourceName })}</h2>

      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}

      {login === null ? (
        <>
          <p>{t("login.youSignIn")}</p>
          <p>{t("login.neverStored")}</p>
          <p className="cards__meta">{t("login.scoped")}</p>
        </>
      ) : (
        <>
          {connected ? (
            <p className="notice" role="status">{t("login.connected", { name: sourceName })}</p>
          ) : (
            <>
              {outcome?.outcome === "not_logged_in" && (
                <p className="notice notice--problem" role="status">{t("login.notSignedIn")}</p>
              )}
              <img ref={frame} className="login__frame" tabIndex={0} alt={t("login.frameAlt")}
                   src={`/api/logins/${login.login_id}/frame?f=${tick}`}
                   onClick={onClick} onKeyDown={onKeyDown}
                   onLoad={() => {
                     if (timer.current !== null) window.clearTimeout(timer.current);
                     timer.current = window.setTimeout(() => setTick((n) => n + 1), 150);
                   }} />
              <p className="cards__meta">{t("login.relayHelp")}</p>
            </>
          )}
        </>
      )}

      <div className="confirm__actions">
        <button type="button" className="button" onClick={() => void cancel()}>
          {connected ? t("login.done") : t("common.cancel")}
        </button>
        {login === null && (
          <button type="button" className="button button--primary" disabled={busy} onClick={() => void open()}>
            {t("login.open")}
          </button>
        )}
        {login !== null && !connected && (
          <button type="button" className="button button--primary" disabled={busy} onClick={() => void complete()}>
            {t("login.signedIn")}
          </button>
        )}
      </div>
    </div>
  );
}
