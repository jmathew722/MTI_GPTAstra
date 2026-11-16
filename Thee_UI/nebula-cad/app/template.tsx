"use client";

import { motion } from "motion/react";
import { dur, ease } from "@/lib/motion";

/** Route transition: a short cross-fade with a subtle shift. Templates remount on navigation. */
export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: dur.standard, ease: ease.out }}>
      {children}
    </motion.div>
  );
}
