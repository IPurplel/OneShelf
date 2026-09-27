import { useLayoutEffect, useRef, useState } from "react";

/** Measure the shelf itself: CSS owns the card width/gap at each breakpoint. */
export function useShelfColumns() {
  const ref = useRef<HTMLElement>(null);
  const [columns, setColumns] = useState(1);

  useLayoutEffect(() => {
    const shelf = ref.current;
    if (!shelf || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      const style = getComputedStyle(shelf);
      const width = parseFloat(style.getPropertyValue("--shelf-card-width"));
      const gap = parseFloat(style.getPropertyValue("--shelf-card-gap"));
      if (width > 0 && Number.isFinite(gap)) {
        setColumns(Math.max(1, Math.floor((shelf.clientWidth + gap) / (width + gap))));
      }
    };
    const observer = new ResizeObserver(measure);
    observer.observe(shelf);
    measure();
    return () => observer.disconnect();
  }, []);

  return { ref, columns };
}
