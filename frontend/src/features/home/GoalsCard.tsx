import { type FormEvent, useState } from "react";

import { api } from "@/api/client";
import { useResource } from "@/api/useApi";
import { Icon } from "@/components/Icon";
import { useI18n } from "@/i18n/i18n";

type Goals = {
  books: { year: number; goal: number | null; finished: number; expected_by_now: number | null; ahead: number | null };
  streak: { current: number; longest: number; read_today: boolean; last_7: boolean[] };
};

/** The reader's own day: getTimezoneOffset() is UTC minus local, which is what the library expects. */
const offset = () => new Date().getTimezoneOffset();

/**
 * Reading goals on Home: the year's books against a goal you set, and a daily streak. The words do the
 * motivating: how far ahead or behind the pace you are, and what one page today would make of the streak.
 */
export function GoalsCard() {
  const { t, tn, errorText } = useI18n();
  const { data, reload } = useResource<Goals>("/api/goals", { offset: offset() });
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  // Goals are an encouragement, never a blocker: anything unexpected and the card simply is not shown.
  if (data === null || !data.books || !data.streak) return null;
  const { books, streak } = data;

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const books_per_year = value.trim() === "" ? null : Number(value);
    setProblem(null);
    try {
      await api.put(`/api/goals?offset=${offset()}`, { books_per_year });
      setEditing(false);
      reload();
    } catch (error) {
      setProblem(errorText(error));
    }
  };
  const startEditing = () => { setValue(books.goal ? String(books.goal) : "12"); setEditing(true); };

  // A goal set late in the year starts far "behind"; past a small gap, what is left becomes a plan instead.
  const remaining = books.goal ? Math.max(0, books.goal - books.finished) : 0;
  const now = new Date();
  const daysLeft = Math.ceil((new Date(now.getFullYear() + 1, 0, 1).getTime()
    - new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / 86_400_000);
  const pace = books.ahead === null ? null
    : books.ahead > 0 ? tn("goals.ahead", books.ahead)
    : books.ahead === 0 ? t("goals.onPace")
    : books.ahead >= -2 ? tn("goals.behind", -books.ahead)
    : tn("goals.plan", remaining, { every: Math.max(1, Math.floor(daysLeft / Math.max(1, remaining))) });
  const fill = books.goal ? Math.min(1, books.finished / books.goal) : 0;
  const nudge = streak.read_today ? t("goals.readToday")
    : streak.current > 0 ? t("goals.keepGoing", { next: streak.current + 1 }) : t("goals.startToday");

  return (
    <section className="goals" aria-labelledby="goals-title">
      <h2 className="display goals__title" id="goals-title">{t("goals.title")}</h2>
      {problem !== null && <p className="notice notice--problem" role="alert">{problem}</p>}
      <div className="goals__panels">
        <div className="goals__panel">
          {editing ? (
            <form className="goals__edit" onSubmit={(event) => void save(event)}>
              <label>
                <span>{t("goals.booksThisYear")}</span>
                <input className="field" type="number" min={1} max={1000} inputMode="numeric" value={value}
                       onChange={(event) => setValue(event.target.value)} autoFocus />
              </label>
              <button type="submit" className="button button--primary">{t("shelves.save")}</button>
              <button type="button" className="button" onClick={() => setEditing(false)}>{t("common.cancel")}</button>
            </form>
          ) : books.goal ? (
            <>
              <p className="goals__figure">{t("goals.books", { finished: books.finished, goal: books.goal, year: books.year })}</p>
              <span className="goals__bar" aria-hidden="true"><span style={{ transform: `scaleX(${fill})` }} /></span>
              {pace && <p className="goals__note">{pace}</p>}
              <button type="button" className="chip" onClick={startEditing}>{t("goals.change")}</button>
            </>
          ) : (
            <>
              <p className="goals__figure">{tn("goals.finishedNoGoal", books.finished, { year: books.year })}</p>
              <p className="goals__note">{t("goals.noGoal")}</p>
              <button type="button" className="chip chip--accent" onClick={startEditing}>{t("goals.set")}</button>
            </>
          )}
        </div>
        <div className="goals__panel">
          <p className="goals__figure goals__streak">
            <Icon name="flame" size={22} />{tn("goals.streak", streak.current)}
          </p>
          <ol className="goals__week" aria-label={t("goals.week")}>
            {streak.last_7.map((read, index) => (
              <li key={index} className={read ? "goals__day goals__day--read" : "goals__day"}
                  aria-label={t(read ? "goals.dayRead" : "goals.dayMissed")} />
            ))}
          </ol>
          <p className="goals__note">{nudge}</p>
          {streak.longest > streak.current && <p className="cards__meta">{tn("goals.longest", streak.longest)}</p>}
        </div>
      </div>
    </section>
  );
}
