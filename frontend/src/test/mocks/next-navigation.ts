import { useSyncExternalStore } from "react";

type Listener = () => void;

const listeners = new Set<Listener>();

function currentUrl() {
  return `${window.location.pathname}${window.location.search}${window.location.hash}`;
}

function subscribe(listener: Listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify() {
  listeners.forEach((listener) => listener());
}

export function setTestUrl(href: string, replace = true) {
  const destination = new URL(href, window.location.origin);
  const nextUrl = `${destination.pathname}${destination.search}${destination.hash}`;
  if (nextUrl === currentUrl()) return;
  window.history[replace ? "replaceState" : "pushState"]({}, "", nextUrl);
  notify();
}

function useUrl() {
  return useSyncExternalStore(subscribe, currentUrl, currentUrl);
}

const router = {
  push: (href: string) => setTestUrl(href, false),
  replace: (href: string) => setTestUrl(href, true),
  refresh: () => notify(),
  prefetch: async () => undefined,
  back: () => window.history.back(),
  forward: () => window.history.forward()
};

export function useRouter() {
  return router;
}

export function usePathname() {
  return new URL(useUrl(), window.location.origin).pathname;
}

export function useSearchParams() {
  return new URLSearchParams(new URL(useUrl(), window.location.origin).search);
}

export function useParams() {
  const pathname = usePathname();
  const contract = pathname.match(/^\/(?:admin\/)?contracts\/([^/]+)/);
  if (contract) return { contractId: decodeURIComponent(contract[1]) };
  const user = pathname.match(/^\/admin\/users\/([^/]+)/);
  if (user) return { userId: decodeURIComponent(user[1]) };
  return {};
}
