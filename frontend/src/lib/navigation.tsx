"use client";

import NextLink from "next/link";
import { useParams as useNextParams, usePathname, useRouter, useSearchParams as useNextSearchParams } from "next/navigation";
import { forwardRef, useCallback, useEffect } from "react";
import type { AnchorHTMLAttributes, ReactNode } from "react";

type NavigationOptions = { replace?: boolean };
type SearchParamsInit = URLSearchParams | Record<string, string>;

type CompatLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  to: string;
  children?: ReactNode;
};

export const Link = forwardRef<HTMLAnchorElement, CompatLinkProps>(function Link({ to, ...props }, ref) {
  return <NextLink ref={ref} href={to} {...props} />;
});

type NavLinkProps = CompatLinkProps & { end?: boolean };

export const NavLink = forwardRef<HTMLAnchorElement, NavLinkProps>(function NavLink({ to, end, className, ...props }, ref) {
  const pathname = usePathname();
  const active = end ? pathname === to : pathname === to || pathname.startsWith(`${to}/`);
  return <Link ref={ref} to={to} className={className} aria-current={active ? "page" : undefined} {...props} />;
});

export function useNavigate() {
  const router = useRouter();
  return useCallback((to: string, options: NavigationOptions = {}) => {
    if (options.replace) router.replace(to);
    else router.push(to);
  }, [router]);
}

export function useLocation() {
  const pathname = usePathname();
  const params = useNextSearchParams();
  const search = params.toString();
  return { pathname, search: search ? `?${search}` : "" };
}

export function useParams<T extends Record<string, string | string[] | undefined> = Record<string, string>>() {
  return useNextParams<T>();
}

export function useSearchParams() {
  const params = useNextSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const setParams = useCallback((next: SearchParamsInit, options: NavigationOptions = {}) => {
    const search = new URLSearchParams(next).toString();
    const href = `${pathname}${search ? `?${search}` : ""}`;
    if (options.replace) router.replace(href);
    else router.push(href);
  }, [pathname, router]);
  return [params, setParams] as const;
}

export function Navigate({ to, replace = false }: { to: string; replace?: boolean }) {
  const navigate = useNavigate();
  useEffect(() => {
    navigate(to, { replace });
  }, [navigate, replace, to]);
  return null;
}
