import { useCallback, useEffect, useId, useState } from "react";

import { ApiError, api } from "@/api/client";
import { Drawer } from "@/components/Drawer";
import { useI18n } from "@/i18n/i18n";
import type { StringKey } from "@/i18n/strings";
import { explain } from "./permissions";

type RegistryState = "installed" | "available" | "update_available" | "pending_review" | "installed_newer"
  | "incompatible";

type Card = {
  id: string;
  name: string;
  version: string;
  trust_label: string;
  signed: boolean;
  effective_trust: string;
  api: string | null;
  state: RegistryState;
  installed_version: string | null;
  plugin_state: string | null;
  channel: string | null;
  installed_trust: string | null;
};

type Listing = { configured: boolean; location?: string; plugins: Card[] };

type Review = {
  id: string;
  name: string;
  version: string;
  publisher: string | null;
  description: string | null;
  capabilities: string[];
  permissions: string[];
  added_permissions: string[];
  tests_passed: boolean;
  test_cases: number;
  test_failures: string[];
  effective_trust: string;
  claimed_trust: string;
  signed: boolean;
  sha256: string;
  state: RegistryState;
  installed_version: string | null;
  plugin_state: string | null;
};

type Outcome = { plugin_id: string; version: string; state: string };

/** What a card offers. Installed, newer-installed and incompatible cards offer nothing at all. */
const ACTION: Partial<Record<RegistryState, StringKey>> = {
  available: "registry.action.install",
  update_available: "registry.action.update",
  pending_review: "registry.action.review",
};

/** The trust a person can rely on: a trusted signature, never what the index merely claims. */
function trustKey(effective: string, claimed: string): StringKey {
  if (effective === "official") return "registry.trust.official";
  if (effective === "verified_community") return "registry.trust.verified";
  if (effective === "invalid_signature") return "registry.trust.invalid";
  if (claimed === "official") return "registry.trust.unverified";
  if (claimed === "verified_community") return "registry.trust.unverifiedVerified";
  return "registry.trust.community";
}

/**
 * Sources → Source Registry (REL-13; mixed trust since the Registry moved to OneShelf-Adapters).
 *
 * The Registry is read against the library by Core, so each card already knows whether it is installed,
 * an update, waiting for review, older than what is installed, or too new for this OneShelf. Every
 * install, reinstall and update goes through the same review a file upload gets, and the install request
 * carries the sha256 of the package that was reviewed — if the Registry changed underneath, it is
 * refused. Reading the Registry changes nothing; if it cannot be reached, installed sources are
 * untouched and this section simply says so.
 */
export function RegistryPanel({ revision, onChanged }: { revision: number; onChanged: () => void }) {
  const { t } = useI18n();
  const heading = useId();
  const [listing, setListing] = useState<Listing | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [reviewing, setReviewing] = useState<Card | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (refresh: boolean) => {
    try {
      setListing(await api.get<Listing>("/api/registry", refresh ? { refresh: true } : undefined));
      setUnavailable(false);
    } catch {
      setUnavailable(true);
    }
  }, []);

  useEffect(() => { void load(false); }, [load, revision]);

  const close = useCallback(() => { setReviewing(null); setReview(null); setProblem(null); }, []);

  const open = async (card: Card) => {
    setDone(null);
    setProblem(null);
    setReview(null);
    setReviewing(card);
    setBusy(true);
    try {
      setReview(await api.post<Review>("/api/registry/review-package", { plugin_id: card.id, version: card.version }));
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setBusy(false);
    }
  };

  const install = async () => {
    if (review === null) return;
    setProblem(null);
    setBusy(true);
    try {
      const outcome = await api.post<Outcome>("/api/registry/install", {
        plugin_id: review.id, version: review.version,
        approved_permissions: review.permissions, sha256: review.sha256,
      });
      const key: StringKey = outcome.state === "pending_review" ? "registry.done.pending" : "registry.done.installed";
      setDone(t(key, { name: review.name, version: review.version }));
      close();
      onChanged();
      void load(false);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : t("state.offline"));
    } finally {
      setBusy(false);
    }
  };

  const status = (card: Card): string => {
    const disabled = card.plugin_state === "disabled";
    switch (card.state) {
      case "installed":
        return disabled ? t("registry.state.installedDisabled") : t("registry.state.installed");
      case "available":
        return t("registry.state.available");
      case "update_available":
        return t(disabled ? "registry.state.updateDisabled" : "registry.state.update",
                 { from: card.installed_version ?? "", to: card.version });
      case "pending_review":
        return t("registry.state.pending", { version: card.version });
      case "installed_newer":
        return t("registry.state.newer", { version: card.installed_version ?? "" });
      case "incompatible":
        return t("registry.state.incompatible");
    }
  };

  const plugins = listing?.plugins ?? [];
  const buttonKey: StringKey = review?.state === "update_available" ? "registry.review.update"
    : review?.state === "pending_review" ? "registry.review.approve" : "install.action";

  return (
    <section className="paper" aria-labelledby={heading}>
      <h2 className="display" id={heading}>{t("registry.title")}</h2>
      <p className="firstrun__lede">{t("registry.help")}</p>

      {done !== null && <p className="notice" role="status">{done}</p>}

      {unavailable && (
        <div className="notice notice--problem">
          <p>{t("registry.unavailable")}</p>
          <button type="button" className="button" onClick={() => void load(true)}>{t("registry.retry")}</button>
        </div>
      )}
      {listing !== null && !listing.configured && <p className="cards__meta">{t("registry.notConfigured")}</p>}

      {plugins.length > 0 && (
        <ul className="cards">
          {plugins.map((card) => {
            const action = ACTION[card.state];
            return (
              <li key={card.id} className="cards__row">
                <span className="cards__name display">{card.name}</span>
                <span className="cards__meta">{card.version}</span>
                <span className="chip chip--static">{t(trustKey(card.effective_trust, card.trust_label))}</span>
                <span className={`cards__state cards__state--${card.state}`}>{status(card)}</span>
                {action !== undefined && (
                  <button type="button" className="chip" disabled={busy} onClick={() => void open(card)}>
                    {t(action)}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {reviewing !== null && (
        <Drawer title={t("registry.review.title", { name: reviewing.name })} onClose={close}>
          {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
          {review === null && problem === null && <p className="cards__meta">{t("registry.review.checking")}</p>}
          {review !== null && (
            <div className="install__review">
              <dl className="details">
                <dt>{t("install.name")}</dt><dd>{review.name}</dd>
                <dt>{t("install.publisher")}</dt><dd>{review.publisher ?? t("install.noPublisher")}</dd>
                <dt>{t("install.version")}</dt>
                <dd>{review.installed_version !== null && review.installed_version !== review.version
                  ? `${review.installed_version} → ${review.version}` : review.version}</dd>
                <dt>{t("sources.trust")}</dt><dd>{t(trustKey(review.effective_trust, review.claimed_trust))}</dd>
                <dt>{t("sources.capabilities")}</dt><dd>{review.capabilities.join(", ")}</dd>
              </dl>
              {review.description !== null && <p>{review.description}</p>}

              <h3 className="display">{t("install.permissions")}</h3>
              <ul className="install__permissions">
                {review.permissions.map((permission) => {
                  // "New" only means something against a version already installed.
                  const added = review.installed_version !== null && review.added_permissions.includes(permission);
                  return (
                    <li key={permission} className={added ? "install__added" : undefined}>
                      <span>
                        {explain(permission, t)}
                        {added && <> <strong className="chip chip--static">{t("registry.review.new")}</strong></>}
                      </span>
                      <code className="cards__meta">{permission}</code>
                    </li>
                  );
                })}
              </ul>
              <p className="cards__meta">{t("install.permissionsNote")}</p>
              {review.plugin_state === "disabled" && <p className="cards__meta">{t("registry.review.staysDisabled")}</p>}

              <h3 className="display">{t("install.tests")}</h3>
              {review.tests_passed ? (
                <p className="cards__ok">{t("install.testsPassed", { cases: review.test_cases })}</p>
              ) : (
                <>
                  <p className="cards__warn">{t("install.testsFailed")}</p>
                  <ul className="restore__issues">
                    {review.test_failures.map((failure) => <li key={failure}>{failure}</li>)}
                  </ul>
                </>
              )}

              {review.tests_passed && (
                <div className="firstrun__actions">
                  <button type="button" className="button button--primary" disabled={busy}
                          onClick={() => void install()}>
                    {t(buttonKey, { version: review.version })}
                  </button>
                  <button type="button" className="button" onClick={close}>{t("common.cancel")}</button>
                </div>
              )}
            </div>
          )}
        </Drawer>
      )}
    </section>
  );
}
