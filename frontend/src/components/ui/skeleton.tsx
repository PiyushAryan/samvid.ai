import type { HTMLAttributes } from "react";

type SkeletonProps = HTMLAttributes<HTMLDivElement>;

export function Skeleton({ className, ...props }: SkeletonProps) {
  return (
    <div
      data-slot="skeleton"
      className={["skeleton", className].filter(Boolean).join(" ")}
      aria-hidden="true"
      {...props}
    />
  );
}
