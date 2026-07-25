import { CSSProperties, ElementType, JSX, memo, useMemo } from "react";
import { motion, useReducedMotion } from "motion/react";

export type TextShimmerProps = {
  children: string;
  as?: ElementType;
  className?: string;
  duration?: number;
  spread?: number;
};

function TextShimmerComponent({
  children,
  as: Component = "span",
  className,
  duration = 2,
  spread = 2
}: TextShimmerProps) {
  const prefersReducedMotion = useReducedMotion();
  const MotionComponent = motion.create(Component as keyof JSX.IntrinsicElements);
  const dynamicSpread = useMemo(() => children.length * spread, [children, spread]);

  return (
    <MotionComponent
      className={["text-shimmer", className].filter(Boolean).join(" ")}
      initial={prefersReducedMotion ? false : { backgroundPosition: "100% center" }}
      animate={prefersReducedMotion ? undefined : { backgroundPosition: "0% center" }}
      transition={{
        repeat: Infinity,
        duration,
        ease: "linear"
      }}
      style={{
        "--text-shimmer-spread": `${dynamicSpread}px`
      } as CSSProperties}
    >
      {children}
    </MotionComponent>
  );
}

export const TextShimmer = memo(TextShimmerComponent);
