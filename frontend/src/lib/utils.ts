type ClassValue = string | false | null | undefined;

/** Lightweight class joiner for the locally-installed shadcn/AI Elements code. */
export function cn(...values: ClassValue[]) {
  return values.filter(Boolean).join(" ");
}
