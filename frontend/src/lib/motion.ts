export { useReducedMotion } from "motion/react";

export const TRANSITION_SPRING = { type: "spring" as const, stiffness: 300, damping: 30 };
export const TRANSITION_EASE = { duration: 0.2, ease: [0.2, 0, 0.2, 1] as const };
export const TRANSITION_SLOW = { duration: 0.26, ease: [0.2, 0, 0.2, 1] as const };
