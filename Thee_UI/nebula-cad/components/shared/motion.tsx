"use client";

import * as React from "react";
import { AnimatePresence, animate, motion, useScroll, useSpring, type HTMLMotionProps } from "motion/react";
import { dur, ease, fadeUp, stagger } from "@/lib/motion";
import { cn } from "@/lib/utils";

/** Fades and lifts into view once, when scrolled to. */
export function Reveal({ children, delay = 0, className, ...rest }: { children: React.ReactNode; delay?: number; className?: string } & Omit<HTMLMotionProps<"div">, "children">) {
  return (
    <motion.div initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ duration: dur.entrance, ease: ease.out, delay }} className={className} {...rest}>
      {children}
    </motion.div>
  );
}

/** A container whose StaggerItem children rise in one after another on mount. */
export function StaggerList({ children, className, as = "div", delay = 0.05, each = 0.06 }: { children: React.ReactNode; className?: string; as?: "div" | "ul" | "ol"; delay?: number; each?: number }) {
  const Tag = motion[as] as typeof motion.div;
  return (
    <Tag variants={stagger(delay, each)} initial="hidden" animate="show" className={className}>
      {children}
    </Tag>
  );
}
export function StaggerItem({ children, className, as = "div" }: { children: React.ReactNode; className?: string; as?: "div" | "li" | "section" }) {
  const Tag = motion[as] as typeof motion.div;
  return (
    <Tag variants={fadeUp} className={className}>
      {children}
    </Tag>
  );
}

/** Height-animated disclosure. The content is unmounted when closed. */
export function Collapse({ open, children, className }: { open: boolean; children: React.ReactNode; className?: string }) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: dur.standard, ease: ease.out }}
          className={cn("overflow-hidden", className)}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Tweens to every new value (not only the first), so edits feel connected to their result. */
export function AnimatedNumber({ value, format, className }: { value: number; format: (n: number) => string; className?: string }) {
  const ref = React.useRef<HTMLSpanElement>(null);
  const prev = React.useRef(value);
  const fmt = React.useRef(format);
  React.useEffect(() => {
    fmt.current = format;
  });
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduced = document.documentElement.dataset.motion === "reduced" || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || prev.current === value) {
      el.textContent = fmt.current(value);
      prev.current = value;
      return;
    }
    const from = prev.current;
    prev.current = value;
    const c = animate(from, value, { duration: 0.6, ease: [0.22, 1, 0.36, 1], onUpdate: (v) => (el.textContent = fmt.current(v)), onComplete: () => (el.textContent = fmt.current(value)) });
    return () => c.stop();
  }, [value]);
  return (
    <span ref={ref} className={className}>
      {format(value)}
    </span>
  );
}

/** Thin gold bar at the top of the viewport showing reading progress. */
export function ScrollProgress() {
  const { scrollYProgress } = useScroll();
  const x = useSpring(scrollYProgress, { stiffness: 220, damping: 32, mass: 0.4 });
  return <motion.div aria-hidden style={{ scaleX: x }} className="fixed inset-x-0 top-0 z-[60] h-0.5 origin-left bg-gradient-to-r from-[#A67CFF] to-gold" />;
}

/** Sets --mx/--my on the hovered `.lift` card so its CSS spotlight follows the pointer. One listener for the whole app. */
export function PointerGlow() {
  React.useEffect(() => {
    let raf = 0;
    const onMove = (e: PointerEvent) => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        const el = (e.target as HTMLElement | null)?.closest?.(".lift") as HTMLElement | null;
        if (!el) return;
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${e.clientX - r.left}px`);
        el.style.setProperty("--my", `${e.clientY - r.top}px`);
      });
    };
    document.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      document.removeEventListener("pointermove", onMove);
      if (raf) cancelAnimationFrame(raf);
    };
  }, []);
  return null;
}
