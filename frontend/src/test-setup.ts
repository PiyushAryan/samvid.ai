import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

vi.mock("next/navigation", async () => import("./test-navigation"));
vi.mock("next/link", async () => import("./test-link"));

afterEach(async () => {
  cleanup();
  const { setTestUrl } = await import("./test-navigation");
  setTestUrl("/");
});
