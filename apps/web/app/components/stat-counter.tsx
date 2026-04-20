"use client";

import { useEffect, useRef } from "react";
import { animate, useInView, useMotionValue, useTransform, motion } from "framer-motion";

/**
 * Animated number that ticks up from 0 to `value` once it scrolls into view.
 * Used for the "1,300+" / "0" / "∞" hero stats.
 */
export function StatCounter({
  value,
  prefix = "",
  suffix = "",
  duration = 1.6,
  formatter,
}: {
  value: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  formatter?: (n: number) => string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -10% 0px" });
  const count = useMotionValue(0);
  const display = useTransform(count, (n) => {
    const fmt = formatter ?? ((x: number) => Math.round(x).toLocaleString());
    return `${prefix}${fmt(n)}${suffix}`;
  });

  useEffect(() => {
    if (!inView) return;
    const controls = animate(count, value, {
      duration,
      ease: [0.16, 1, 0.3, 1],
    });
    return () => controls.stop();
  }, [inView, count, value, duration]);

  return <motion.span ref={ref}>{display}</motion.span>;
}
