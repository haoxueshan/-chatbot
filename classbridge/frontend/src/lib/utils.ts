import { clsx, type ClassValue } from "clsx";

// Component variants use semantic classes; callers can extend with className.
export function cn(...values: ClassValue[]) {
  return clsx(values);
}
