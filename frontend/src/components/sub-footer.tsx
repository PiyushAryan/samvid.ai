import { ArrowRight } from "lucide-react";

import { Link } from "../next-router-compat";

export function SubFooter() {
  return (
    <section className="subfooter-cta" aria-labelledby="subfooter-cta-heading">
      <div className="subfooter-cta-card">
        <img
          className="subfooter-river"
          src="/river.png"
          alt=""
          aria-hidden="true"
          width={1536}
          height={1024}
          loading="lazy"
          decoding="async"
        />
        <svg className="subfooter-thread" aria-hidden="true" viewBox="0 0 1000 200" preserveAspectRatio="none">
          <path d="M72 163C130 109 163 183 230 146c40-22 25-70 82-60 52 9 74 74 125 45 58-33 51-91 116-65 40 16 34 69 93 57 65-14 87-92 148-70 37 13 29 74 106 88" />
          <path d="M109 172c48-18 44-70 93-51 37 14 38 53 78 35 28-13 15-42 54-48" />
        </svg>
        <img
          className="subfooter-swan"
          src="/swan-non.png"
          alt=""
          aria-hidden="true"
          width={1024}
          height={1024}
          loading="lazy"
          decoding="async"
        />

        <div className="subfooter-cta-content">
          <div className="subfooter-brand" aria-label="Samvid">
            <picture className="subfooter-brand-mark" aria-hidden="true">
              <source media="(prefers-color-scheme: dark)" srcSet="/favicon-light.svg" />
              <img src="/favicon-dark.svg" alt="" width={28} height={28} />
            </picture>
            <span>Samvid</span>
          </div>
          <h2 id="subfooter-cta-heading">
            Separate <span>risk</span> from signal.
          </h2>
          <p className="subfooter-cta-copy">
            Review every clause with clarity and confidence. Surface hidden risks before they become your burden.
          </p>
          <div className="subfooter-cta-actions">
            <Link to="/book-demo" className="btn-lp-primary">
              Book a Demo <ArrowRight size={16} aria-hidden="true" />
            </Link>
            <a href="#workflow" className="btn-lp-secondary">See how it works</a>
          </div>
        </div>
      </div>
    </section>
  );
}
