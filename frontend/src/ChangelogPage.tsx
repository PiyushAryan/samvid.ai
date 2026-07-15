import { ArrowLeft, ArrowRight, Check, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import "./home.css";
import "./changelog.css";

const releases = [
  {
    date: "July 16, 2026",
    version: "v0.3.0",
    title: "The Samvid workspace is live",
    summary: "The first complete contract intelligence workspace brings review, evidence, versions, and signer tracking into one focused operating surface.",
    icon: Sparkles,
    tags: ["New", "Workspace"],
    changes: [
      "AI-assisted clause analysis with evidence-grounded risk findings and recommended next actions.",
      "Contract list, detail, original-document preview, and review status filters in one workspace.",
      "Responsive navigation that keeps the workspace easy to reach across desktop and mobile."
    ]
  },
  {
    date: "July 10, 2026",
    version: "v0.2.0",
    title: "Email ingestion and document history",
    summary: "Contracts can now enter the review pipeline from email while every uploaded revision remains attributable and accessible.",
    icon: Mail,
    tags: ["Improved", "Ingestion"],
    changes: [
      "Inbound email delivery for forwarding contract attachments directly into a workspace.",
      "Readable text extraction for scanned PDFs and image-based contract documents.",
      "Version-aware document records that keep active signing requests pinned to a specific revision."
    ]
  },
  {
    date: "July 1, 2026",
    version: "v0.1.0",
    title: "Signer status tracking and audit history",
    summary: "Teams can coordinate signing progress without losing the operational history behind each manual status change.",
    icon: ShieldCheck,
    tags: ["New", "Audit"],
    changes: [
      "Signing requests with required and optional signer identities.",
      "Append-only signer events for sent, viewed, signed, declined, expired, and cancelled states.",
      "Clear execution disclaimer separating workflow tracking from legally binding e-signature services."
    ]
  }
];

export function ChangelogPage() {
  return (
    <div className="changelog-page">
      <header className="changelog-navbar">
        <div className="changelog-navbar-inner">
          <Link to="/" className="changelog-brand" aria-label="Samvid home">
            <span className="changelog-brand-name">Samvid</span>
            <span className="changelog-brand-tag">Intelligence</span>
          </Link>

          <nav className="changelog-navbar-links" aria-label="Primary navigation">
            <Link to="/" className="changelog-navbar-link">Home</Link>
            <Link to="/#features" className="changelog-navbar-link">Features</Link>
            <span className="changelog-navbar-link active" aria-current="page">Changelog</span>
          </nav>

          <div className="changelog-navbar-actions">
            <Link to="/contracts" className="btn-lp-secondary">Sign up</Link>
            <Link to="/contracts" className="btn-lp-primary">Book a Demo</Link>
          </div>
        </div>
      </header>

      <main className="changelog-main">
        <section className="changelog-intro">
          <Link to="/" className="changelog-back-link">
            <ArrowLeft size={14} /> Back to Samvid
          </Link>
          <div className="changelog-intro-grid">
            <div>
              <p className="changelog-eyebrow">Product updates</p>
              <h1>Changelog</h1>
            </div>
            <p className="changelog-intro-copy">
              New capabilities, workflow improvements, and reliability updates across the Samvid contract intelligence workspace.
            </p>
          </div>
        </section>

        <section className="release-list" aria-label="Product releases">
          {releases.map(({ date, version, title, summary, icon: Icon, tags, changes }, index) => (
            <article className="release-entry" key={version}>
              <div className="release-meta">
                <time dateTime={date}>{date}</time>
                <span>{version}</span>
              </div>

              <div className="release-rail" aria-hidden="true">
                <span className="release-marker"><Icon size={16} /></span>
              </div>

              <div className="release-content">
                <div className="release-heading">
                  <div>
                    <div className="release-tags">
                      {tags.map((tag) => <span key={tag}>{tag}</span>)}
                      {index === 0 && <span className="latest-tag">Latest</span>}
                    </div>
                    <h2>{title}</h2>
                  </div>
                </div>
                <p className="release-summary">{summary}</p>
                <ul className="release-changes">
                  {changes.map((change) => (
                    <li key={change}><Check size={15} /> <span>{change}</span></li>
                  ))}
                </ul>
              </div>
            </article>
          ))}
        </section>

        <section className="changelog-cta">
          <div>
            <p className="changelog-eyebrow">Available now</p>
            <h2>Put the latest release to work.</h2>
            <p>Review contracts, inspect evidence, and coordinate signer status from the Samvid workspace.</p>
          </div>
          <Link to="/contracts" className="btn-lp-primary">
            Open workspace <ArrowRight size={15} />
          </Link>
        </section>
      </main>

      <footer className="changelog-footer">
        <span>Samvid Intelligence</span>
        <span>&copy; {new Date().getFullYear()} Samvid</span>
      </footer>
    </div>
  );
}
