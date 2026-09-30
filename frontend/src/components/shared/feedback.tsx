import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

type QueryStateProps = {
  query: { isLoading: boolean; isError: boolean; error: unknown };
  children: ReactNode;
  loadingFallback?: ReactNode;
};

export function QueryState({ query, children, loadingFallback }: QueryStateProps) {
  if (query.isLoading) {
    return loadingFallback || <div className="state"><Loader2 className="spin" size={18} /> Loading</div>;
  }
  if (query.isError) {
    return <div className="state error"><AlertTriangle size={18} /> {query.error instanceof Error ? query.error.message : "Something went wrong."}</div>;
  }
  return <>{children}</>;
}

export function MutationError({ mutation }: { mutation: { isError: boolean; error: unknown } }) {
  if (!mutation.isError) return null;
  return <p className="form-error" role="alert">{mutation.error instanceof Error ? mutation.error.message : "Request failed."}</p>;
}
