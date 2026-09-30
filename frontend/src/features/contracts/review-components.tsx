"use client";

import { ChevronRight, FileText } from "lucide-react";
import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import {
  InlineCitation,
  InlineCitationCard,
  InlineCitationCardBody,
  InlineCitationCardTrigger,
  InlineCitationQuote
} from "@/components/ai-elements/inline-citation";
import type { ContractReview } from "./types";
import { cx, EmptyState, PanelTitle, StatusBadge } from "./ui";

const mutedText = "muted";
const panelClass = "panel";
const panelCardClass = "panel panel-card";

function formatConfidence(confidence: number) {
  return `${Math.round(confidence * 100)}% confidence`;
}

function nextActionSummary(recommendation: string): string {
  if (/legal review|legal counsel|counsel|lawyer/i.test(recommendation)) {
    return "Request legal review before accepting or signing.";
  }
  if (/request revisions|negotiate|redline/i.test(recommendation)) {
    return "Request revisions before accepting or signing.";
  }
  return "Review the identified findings before proceeding.";
}

function guidanceItems(recommendation: string): string[] {
  const numberedItems = recommendation
    .split(/(?=\d+\)\s)/)
    .map((item) => item.replace(/^\d+\)\s*/, "").trim())
    .filter(Boolean);
  return numberedItems.length > 1 ? numberedItems : [recommendation];
}

export function ReviewTab({ review }: { review: ContractReview | null }) {
  const [guidanceOpen, setGuidanceOpen] = useState(false);
  const reduceMotion = useReducedMotion();
  if (!review) return <EmptyState title="Review is not ready yet." />;

  return (
    <div className="review-tab">
      <section className={cx(panelCardClass, "review-overview")}>
        <div>
          <PanelTitle>Review overview</PanelTitle>
          <p className="review-overview-copy">The essentials to orient your next decision.</p>
        </div>
        <dl className="definition-list review-overview-meta">
          <div>
            <dt>Contract type</dt>
            <dd>{review.contract_type}</dd>
          </div>
          <div>
            <dt>Parties</dt>
            <dd>{review.parties.length || "Not found"}</dd>
          </div>
          <div>
            <dt>Key terms extracted</dt>
            <dd>{review.key_terms.length}</dd>
          </div>
        </dl>
        <div className="review-next-action">
          <span>Next step</span>
          <strong>{nextActionSummary(review.recommended_next_action)}</strong>
          <p>Use the detailed guidance to prepare the right follow-up with the other party or your legal adviser.</p>
          <div className="review-guidance">
            <button
              className="review-guidance-toggle"
              type="button"
              aria-expanded={guidanceOpen}
              aria-controls="review-guidance-content"
              onClick={() => setGuidanceOpen((open) => !open)}
            >
              View detailed guidance
              <ChevronRight className={cx("review-guidance-chevron", guidanceOpen && "open")} size={15} aria-hidden="true" />
            </button>
            <motion.div
              id="review-guidance-content"
              className="review-guidance-content"
              aria-hidden={!guidanceOpen}
              initial={false}
              animate={{ height: guidanceOpen ? "auto" : 0, opacity: guidanceOpen ? 1 : 0 }}
              transition={reduceMotion ? { duration: 0 } : { duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
            >
              <ul>
                {guidanceItems(review.recommended_next_action).map((item) => <li key={item}>{item}</li>)}
              </ul>
            </motion.div>
          </div>
        </div>
      </section>
      <div className="detail-grid review-detail-grid">
        <section className={cx(panelClass, "review-parties")}>
          <div className="review-panel-heading">
            <PanelTitle>Parties</PanelTitle>
            {!!review.parties.length && <span>{review.parties.length}</span>}
          </div>
          <div className="term-list">
            {review.parties.map((party) => (
              <div key={`${party.name}-${party.role || "party"}`}>
                <span>{party.role || "Party"}</span>
                <strong>{party.name}</strong>
              </div>
            ))}
            {!review.parties.length && <span className={mutedText}>No parties extracted.</span>}
          </div>
        </section>
        <section className={panelClass}>
          <PanelTitle>Key terms</PanelTitle>
          <div className="term-list">
            {review.key_terms.map((term) => (
              <div key={term.name}>
                <strong>{term.name}</strong>
                <span>{term.value || "Not found"}</span>
              </div>
            ))}
            {!review.key_terms.length && <span className={mutedText}>No key terms extracted.</span>}
          </div>
        </section>
      </div>
      <p className="review-disclaimer">This review is AI-generated operational assistance and not legal advice.</p>
    </div>
  );
}

export function RisksTab({ review }: { review: ContractReview | null }) {
  if (!review) return <EmptyState title="Risks will appear when the review is ready." />;

  return (
    <div className="risks-tab">
      {review.risks.length ? (
        <div className="risk-list risk-list-register">
          {review.risks.map((risk) => (
            <article key={`${risk.title}-${risk.evidence.page_number}`} className="risk-item">
              <div className="risk-heading">
                <StatusBadge status={risk.severity} />
                <span className="risk-clause-type">{risk.clause_type}</span>
              </div>
              <h2>{risk.title}</h2>
              <p>{risk.explanation}</p>
              <div className="risk-evidence">
                <span className="risk-evidence-label">Evidence</span>
                <InlineCitation className="risk-evidence-citation">
                  <InlineCitationCard>
                    <InlineCitationCardTrigger
                      aria-label={`View evidence from page ${risk.evidence.page_number}: ${risk.evidence.exact_text}`}
                      className="risk-evidence-trigger"
                      sources={[]}
                    >
                      <FileText size={13} aria-hidden="true" />
                      Page {risk.evidence.page_number}
                    </InlineCitationCardTrigger>
                    <InlineCitationCardBody className="risk-evidence-card">
                      <div className="risk-evidence-card-meta">Source evidence · Page {risk.evidence.page_number}</div>
                      <InlineCitationQuote className="risk-evidence-quote">{risk.evidence.exact_text}</InlineCitationQuote>
                    </InlineCitationCardBody>
                  </InlineCitationCard>
                </InlineCitation>
                <span className="risk-confidence">{formatConfidence(risk.confidence)}</span>
              </div>
              <div className="risk-recommendation">
                <span>Recommendation</span>
                <strong>{risk.recommendation}</strong>
              </div>
            </article>
          ))}
        </div>
      ) : <EmptyState title="No evidence-grounded risks found." />}
      <p className="review-disclaimer">This review is AI-generated operational assistance and not legal advice.</p>
    </div>
  );
}

