import { forwardRef } from "react";
import type { AnchorHTMLAttributes, ReactNode } from "react";

type TestLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string | URL;
  children?: ReactNode;
};

const TestLink = forwardRef<HTMLAnchorElement, TestLinkProps>(function TestLink({ href, children, ...props }, ref) {
  return <a ref={ref} href={String(href)} {...props}>{children}</a>;
});

export default TestLink;
