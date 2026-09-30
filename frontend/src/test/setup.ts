import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

vi.mock("next/navigation", async () => import("./mocks/next-navigation"));
vi.mock("next/link", async () => import("./mocks/next-link"));

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", {
  value: ResizeObserverMock,
  writable: true
});

afterEach(async () => {
  cleanup();
  const { setTestUrl } = await import("./mocks/next-navigation");
  setTestUrl("/");
});
