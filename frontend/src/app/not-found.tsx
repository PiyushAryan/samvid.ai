import Link from "next/link";

export default function NotFound() {
  return (
    <main className="auth-route-state">
      <section className="auth-route-state-panel">
        <span>Not found</span>
        <h1>This path has no reviews.</h1>
        <Link href="/">Back to home</Link>
      </section>
    </main>
  );
}
