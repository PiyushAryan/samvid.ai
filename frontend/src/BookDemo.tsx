import { getCalApi } from "@calcom/embed-react";
import React, { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { Link } from "react-router-dom";
import "./book-demo.css";

type WorkflowStage = "Production" | "Pilot" | "Prototyping / Exploring";

const workflowStages: WorkflowStage[] = ["Production", "Pilot", "Prototyping / Exploring"];

export function BookDemoPage() {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [stage, setStage] = useState<WorkflowStage>("Prototyping / Exploring");
  const prefersReducedMotion = useReducedMotion();
  const calTriggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    void (async () => {
      const cal = await getCalApi({ namespace: "virtual-coffee" });
      cal("ui", { hideEventTypeDetails: false, layout: "month_view" });
    })();
  }, []);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    calTriggerRef.current?.click();
  };

  const calConfig = JSON.stringify({
    layout: "month_view",
    useSlotsViewOnSmallScreen: "true",
    name,
    email,
    notes: `${stage} contract workflow: ${workflow}`
  });

  return (
    <main className="book-demo-page">
      <section className="book-demo-story" aria-labelledby="demo-story-title">
        <Link to="/" className="book-demo-back">
          <ArrowLeft size={16} aria-hidden="true" />
          Back to home
        </Link>

        <motion.div
          className="book-demo-story-copy"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
        >
          <p className="book-demo-kicker">Samvid walkthrough</p>
          <h1 id="demo-story-title">Let&apos;s make this demo about your contracts.</h1>
          <p>
            Share where contract work slows down. We&apos;ll prepare around your review,
            approval, and signing workflow instead of giving you a generic product tour.
          </p>
        </motion.div>

      </section>

      <section className="book-demo-form-panel" aria-labelledby="demo-form-title">
        <motion.div
          className="book-demo-form-wrap"
          initial={prefersReducedMotion ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.42, delay: prefersReducedMotion ? 0 : 0.08 }}
        >
          <header className="book-demo-form-heading">
            <p className="book-demo-kicker">A focused introduction</p>
            <h2 id="demo-form-title">Book a demo</h2>
            <p>See how Samvid reviews contracts, explains risk, and keeps every handoff moving.</p>
          </header>

          <form className="book-demo-form" onSubmit={handleSubmit}>
                    <label className="book-demo-field">
                      <span>Name <em>*</em></span>
                      <input
                        name="name"
                        type="text"
                        autoComplete="name"
                        placeholder="Your name"
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        required
                      />
                    </label>

                    <label className="book-demo-field">
                      <span>Work email <em>*</em></span>
                      <input
                        name="email"
                        type="email"
                        autoComplete="email"
                        placeholder="you@company.com"
                        value={email}
                        onChange={(event) => setEmail(event.target.value)}
                        required
                      />
                    </label>

                    <label className="book-demo-field">
                      <span>Where does contract work slow down? <em>*</em></span>
                      <textarea
                        name="workflow"
                        rows={4}
                        placeholder="For example: reviewing vendor terms, tracking approvals, or chasing signatures"
                        value={workflow}
                        onChange={(event) => setWorkflow(event.target.value)}
                        required
                      />
                    </label>

                    <fieldset className="book-demo-stage-field">
                      <legend>What stage is your contract workflow in?</legend>
                      <div className="book-demo-stage-options">
                        {workflowStages.map((option) => (
                          <label key={option} className={stage === option ? "is-selected" : ""}>
                            <input
                              type="radio"
                              name="stage"
                              value={option}
                              checked={stage === option}
                              onChange={() => setStage(option)}
                            />
                            <span>{option}</span>
                          </label>
                        ))}
                      </div>
                    </fieldset>

                <div className="book-demo-form-actions">
                  <button className="book-demo-submit" type="submit">
                    Select date &amp; time <ArrowRight size={12} aria-hidden="true" />
                  </button>
                </div>
          </form>

          <button
            ref={calTriggerRef}
            className="book-demo-cal-trigger"
            type="button"
            data-cal-namespace="virtual-coffee"
            data-cal-link="piyush-aryan-hrnwlm/virtual-coffee"
            data-cal-config={calConfig}
            tabIndex={-1}
            aria-hidden="true"
          >
            Open Cal.com scheduler
          </button>
        </motion.div>
      </section>
    </main>
  );
}
