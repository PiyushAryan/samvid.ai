import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  action?: ReactNode;
};

export function PageHeader({ eyebrow, title, action }: PageHeaderProps) {
  return (
    <header className="page-header">
      <span>
        <small>{eyebrow}</small>
        <h1>{title}</h1>
      </span>
      {action}
    </header>
  );
}
