import { X } from "lucide-react";
import type { ReactNode } from "react";

type DialogProps = {
  title: string;
  children: ReactNode;
  onClose: () => void;
};

export function Dialog({ title, children, onClose }: DialogProps) {
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <div className="dialog-header">
          <h2>{title}</h2>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
