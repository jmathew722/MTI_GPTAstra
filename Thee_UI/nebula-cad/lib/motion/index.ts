import type { Transition, Variants } from "motion/react";

/** Motion tokens (docs/DESIGN_SPEC.md §7). Implemented once, used everywhere. */
export const dur = { micro: 0.16, standard: 0.22, entrance: 0.5 } as const;
export const ease = {
  out: [0.22, 1, 0.36, 1] as [number, number, number, number],
  inOut: [0.65, 0, 0.35, 1] as [number, number, number, number],
};
export const spring: Transition = { type: "spring", stiffness: 380, damping: 32, mass: 0.9 };
export const STAGGER = 0.07;

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: dur.entrance, ease: ease.out } },
};

export const fade: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: dur.entrance, ease: ease.out } },
};

export const slideDown: Variants = {
  hidden: { opacity: 0, y: -14 },
  show: { opacity: 1, y: 0, transition: { duration: dur.entrance, ease: ease.out } },
};

export const stagger = (delayChildren = 0, each = STAGGER): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: each, delayChildren } },
});

export const rowVariants: Variants = {
  hidden: { opacity: 0, y: 6 },
  show: { opacity: 1, y: 0, transition: { duration: dur.standard, ease: ease.out } },
  exit: { opacity: 0, x: -8, transition: { duration: dur.micro } },
};

export const tabContent: Variants = {
  hidden: { opacity: 0, y: 4 },
  show: { opacity: 1, y: 0, transition: { duration: dur.standard, ease: ease.out } },
  exit: { opacity: 0, transition: { duration: 0.12 } },
};

const INTRO_KEY = "nebula-intro-played";

/** The page-load sequence plays once per browser session, not on every navigation. */
export function shouldPlayIntro(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.sessionStorage.getItem(INTRO_KEY) !== "1";
  } catch {
    return false;
  }
}
export function markIntroPlayed(): void {
  try {
    window.sessionStorage.setItem(INTRO_KEY, "1");
  } catch {
    /* storage unavailable: the intro simply replays */
  }
}

export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return true;
  return (
    window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
    document.documentElement.dataset.motion === "reduced"
  );
}
