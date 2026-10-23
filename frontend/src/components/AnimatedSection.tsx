import { motion } from "motion/react";
import type { ReactNode } from "react";

import { TRANSITION_EASE, useReducedMotion } from "@/lib/motion";

const variants = {
  hidden: { opacity: 0, y: 12 },
  visible: { opacity: 1, y: 0 },
};

export function AnimatedSection({
  children,
  className,
  delay = 0,
  tag = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  tag?: "section" | "div" | "article";
} & Record<string, unknown>) {
  const reduced = useReducedMotion();
  const Component = motion[tag];
  return (
    <Component
      className={className}
      initial={reduced ? false : "hidden"}
      animate="visible"
      variants={variants}
      transition={{ ...TRANSITION_EASE, delay }}
      {...rest}
    >
      {children}
    </Component>
  );
}
