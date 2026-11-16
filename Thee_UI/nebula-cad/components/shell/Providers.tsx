"use client";

import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { Toaster } from "sonner";
import { useSettings } from "@/lib/store";
import { markIntroPlayed, shouldPlayIntro } from "@/lib/motion";

/** true only for the first page load of a browser session: drives the one-time entrance sequence */
const IntroContext = React.createContext(false);
export const useIntro = () => React.useContext(IntroContext);

const subscribeNever = () => () => {};

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 4000, refetchOnWindowFocus: false, retry: 1 } },
      }),
  );
  const motion = useSettings((s) => s.motion);
  const density = useSettings((s) => s.density);
  // false on the server and during hydration, true afterwards
  const mounted = React.useSyncExternalStore(subscribeNever, () => true, () => false);
  const [intro] = React.useState(() => shouldPlayIntro());

  React.useEffect(() => {
    const t = setTimeout(markIntroPlayed, 2500);
    return () => clearTimeout(t);
  }, []);

  // Settings -> <html data-*> so CSS, Motion and GSAP all read one switch.
  React.useEffect(() => {
    document.documentElement.dataset.motion = motion;
    document.documentElement.dataset.density = density;
  }, [motion, density]);

  // Pause ambient animation while the tab is hidden.
  React.useEffect(() => {
    const on = () => {
      document.documentElement.dataset.hidden = String(document.hidden);
    };
    on();
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);

  return (
    <QueryClientProvider client={client}>
      <MotionConfig reducedMotion={motion === "reduced" ? "always" : "user"}>
        <IntroContext.Provider value={intro}>
          {/* The app is client-rendered against the adapter layer; rendering after mount
              avoids hydration mismatches from persisted settings and session state. */}
          {mounted ? children : <div className="min-h-dvh" aria-busy="true" />}
        </IntroContext.Provider>
      </MotionConfig>
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#1c1530",
            border: "1px solid rgba(166,124,255,.38)",
            color: "#f7f3fa",
            boxShadow: "0 8px 32px rgba(0,0,0,.45)",
          },
        }}
      />
    </QueryClientProvider>
  );
}
