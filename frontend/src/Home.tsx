import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import {
  FileText,
  Mail,
  Layers,
  Clock,
  ArrowRight,
  Sparkles,
  Check,
  Cpu,
  History,
  AlertTriangle,
  Search
} from "lucide-react";
import "./home.css";

type PreviewStepId = "intake" | "review" | "track";
const MotionLink = motion.create(Link);
const previewSteps: Array<{ id: PreviewStepId; number: string; label: string; title: string; copy: string }> = [
  {
    id: "intake",
    number: "01",
    label: "Inbox",
    title: "One E-mail three tools",
    copy: "Forward any deal. It comes back reviewed, flagged, and ready to sign."
  },
  {
    id: "review",
    number: "02",
    label: "Review",
    title: "Catches what you would miss",
    copy: "Risky clauses and version changes, explained in plain language."
  },
  {
    id: "track",
    number: "03",
    label: "Signature",
    title: "Follow-ups on autopilot",
    copy: "Track opens, schedule nudges, and keep every signer moving."
  }
];

const previewDotTopByStep: Record<PreviewStepId, string> = {
  intake: "7%",
  review: "52%",
  track: "94%"
};

export function LandingPage() {
  const [activePreviewStep, setActivePreviewStep] = useState<PreviewStepId>("intake");
  const [isPastHero, setIsPastHero] = useState(false);
  const [navShift, setNavShift] = useState(0);
  const [edgeShift, setEdgeShift] = useState(0);
  const heroRef = useRef<HTMLElement>(null);
  const demoScrollRef = useRef<HTMLDivElement>(null);
  const previewManualOverrideUntilRef = useRef(0);
  const navRef = useRef<HTMLElement>(null);
  const navCtaRef = useRef<HTMLDivElement>(null);
  const prefersReducedMotion = useReducedMotion();
  const { scrollY } = useScroll();
  const { scrollYProgress: demoScrollProgress } = useScroll({
    target: demoScrollRef,
    offset: ["start start", "end end"]
  });
  const navX = useTransform(scrollY, [0, 320], [0, navShift]);
  const brandX = useTransform(scrollY, [0, 320], [0, -edgeShift]);
  const ctaX = useTransform(scrollY, [0, 320], [0, edgeShift]);
  const smoothDemoProgress = useSpring(demoScrollProgress, { stiffness: 170, damping: 30, mass: 0.32 });
  const demoRailDotTop = useTransform(smoothDemoProgress, [0, 1], ["7%", "94%"]);
  const smoothNavX = useSpring(navX, { stiffness: 180, damping: 28, mass: 0.35 });
  const smoothBrandX = useSpring(brandX, { stiffness: 180, damping: 28, mass: 0.35 });
  const smoothCtaX = useSpring(ctaX, { stiffness: 180, damping: 28, mass: 0.35 });

  useEffect(() => {
    const updateNavbar = () => {
      const heroBottom = heroRef.current?.getBoundingClientRect().bottom ?? 0;
      setIsPastHero(heroBottom <= 80);
    };

    updateNavbar();
    window.addEventListener("scroll", updateNavbar, { passive: true });
    window.addEventListener("resize", updateNavbar);
    return () => {
      window.removeEventListener("scroll", updateNavbar);
      window.removeEventListener("resize", updateNavbar);
    };
  }, []);

  useEffect(() => {
    const measureNavShift = () => {
      const nav = navRef.current;
      const cta = navCtaRef.current;
      const isCompact = typeof window.matchMedia === "function" && window.matchMedia("(max-width: 860px)").matches;
      const nextEdgeShift = isCompact ? 0 : 18;
      setEdgeShift(nextEdgeShift);

      if (!nav || !cta || isCompact) {
        setNavShift(0);
        return;
      }

      const targetShift = cta.offsetLeft - (nav.offsetLeft + nav.offsetWidth) - 24 + nextEdgeShift;
      setNavShift(Math.max(0, targetShift));
    };

    measureNavShift();
    document.fonts?.ready.then(measureNavShift);
    window.addEventListener("resize", measureNavShift);
    return () => window.removeEventListener("resize", measureNavShift);
  }, []);

  useEffect(() => {
    if (prefersReducedMotion) return;

    const unsubscribe = demoScrollProgress.on("change", (latest) => {
      if (Date.now() < previewManualOverrideUntilRef.current) return;
      const nextStep: PreviewStepId = latest < 0.34 ? "intake" : latest < 0.67 ? "review" : "track";
      setActivePreviewStep((previous) => (previous === nextStep ? previous : nextStep));
    });

    return unsubscribe;
  }, [demoScrollProgress, prefersReducedMotion]);

  const activePreviewIndex = previewSteps.findIndex((step) => step.id === activePreviewStep);
  const activePreviewLabel = String(activePreviewIndex + 1).padStart(2, "0");
  const handlePreviewStepSelect = (stepId: PreviewStepId) => {
    previewManualOverrideUntilRef.current = Date.now() + 1800;
    setActivePreviewStep(stepId);

    if (!prefersReducedMotion && demoScrollRef.current) {
      const stepIndex = previewSteps.findIndex((step) => step.id === stepId);
      const track = demoScrollRef.current;
      const trackTop = track.getBoundingClientRect().top + window.scrollY;
      const scrollRange = Math.max(0, track.offsetHeight - window.innerHeight);
      window.scrollTo({
        top: trackTop + scrollRange * (stepIndex / (previewSteps.length - 1)),
        behavior: "smooth"
      });
    }
  };

  return (
    <div className="landing-body">
      <div className="landing-grid-bg"></div>
      <div className="landing-glow-mask"></div>

      <div className="landing-wrapper">
        {/* Navbar */}
        <header className={`landing-header ${isPastHero ? "is-scrolled" : ""}`}>
          <MotionLink
            to="/"
            className="landing-brand"
            style={{ x: prefersReducedMotion ? 0 : smoothBrandX }}
          >
            <div className="landing-brand-text">
              <span className="landing-brand-name">Samvid</span>
              <span className="landing-brand-tag">Intelligence</span>
            </div>
          </MotionLink>
          <motion.nav
            ref={navRef}
            className="landing-nav-links"
            style={{ x: prefersReducedMotion ? 0 : smoothNavX }}
          >
            <a href="#workflow" className="landing-nav-link">How it works</a>
            <Link to="/changelog" className="landing-nav-link">Changelog</Link>
          </motion.nav>
          <motion.div
            ref={navCtaRef}
            className="landing-nav-cta"
            style={{ x: prefersReducedMotion ? 0 : smoothCtaX }}
          >
            <Link to="/chats" className="btn-lp-secondary">
              Sign up
            </Link>
            <a href="#workflow" className="btn-lp-primary">Book a Demo</a>
          </motion.div>
        </header>

        {/* Hero Section */}
        <section ref={heroRef} className="hero-section">
          <div className="hero-content-wrapper">
            <div className="hero-badge">
              BUILT FOR LEGAL & PROCUREMENT TEAMS
            </div>
            <h1 className="hero-heading">
              <span className="hero-heading-lead">One teammate to keep every contract</span>
              <span className="hero-heading-dial">
                <span className="hero-dial-word">review. </span>
                <span className="hero-dial-word">track. </span>
                <span className="hero-dial-word hero-heading-highlight">remember. </span>
              </span>
            </h1>
            <p className="hero-subheading">
              Forward a contract or upload it. Samvid reads every page, explains the risk, keeps every version organized, and records each signing handoff.
            </p>
            <div className="hero-actions">
              <a href="#workflow" className="btn-lp-secondary">
                See how it works
              </a>
              <Link to="/chats" className="btn-lp-primary">
                Open Workspace <ArrowRight size={15} />
              </Link>
              
            </div>
          </div>
          <div className="hero-road" aria-hidden="true">
            <img src="/road-tuktuk-bike.webp" alt="" />
          </div>
        </section>

        <section className="problem-section" aria-labelledby="problem-title">
          <div className="problem-heading">
            <div className="section-kicker">The problem</div>
            <h2 id="problem-title">The contract moves. The context gets left behind.</h2>
            <p>Email, documents, approvals, and follow-ups live in separate places. Your team becomes the manual layer holding every handoff together.</p>
          </div>
          <div className="problem-grid">
            <div className="problem-item">
              <Mail size={18} />
              <span>01 / Inbox</span>
              <h3>The request starts in a thread.</h3>
              <p>Attachments, instructions, and decisions split across replies and forwards.</p>
            </div>
            <div className="problem-item">
              <FileText size={18} />
              <span>02 / Document</span>
              <h3>The risk stays inside the file.</h3>
              <p>Important terms wait for someone to read, explain, and route them manually.</p>
            </div>
            <div className="problem-item">
              <Clock size={18} />
              <span>03 / Follow-up</span>
              <h3>Progress depends on chasing.</h3>
              <p>Approvals and signer updates stall when nobody owns the next reminder.</p>
            </div>
            <div className="problem-item">
              <Layers size={18} />
              <span>04 / Archive</span>
              <h3>The final answer is hard to find.</h3>
              <p>Versions, renewal dates, and past decisions disappear into shared folders.</p>
            </div>
          </div>
          <p className="problem-resolution">Samvid gives those disconnected steps one operating layer, from first document to final status.</p>
        </section>

        {/* Interactive Workspace Simulator */}
        <section id="demo" className="demo-section" aria-label="Interactive workspace demo">
          <div className="demo-heading">
            <div>
              <div className="section-kicker">Interactive product preview</div>
              <h2>Every contract your business touches.</h2>
            </div>
            <p>From email thread to signature, without leaving your inbox.</p>
          </div>

          <div ref={demoScrollRef} className="demo-scroll-track">
            <div className="demo-scroll-sticky">
              <div className="demo-showcase">
                <div className="demo-stage-stack" role="tablist" aria-label="Contract workflow stages">
                  <div className="demo-stage-rail" aria-hidden="true">
                    <svg viewBox="0 0 28 560" preserveAspectRatio="none">
                      <path
                        className="demo-stage-rail-base"
                        d="M14 8 V170 l10 14 v62 l-10 14 v100 l10 14 v62 l-10 14 V552"
                      />
                      <motion.path
                        className="demo-stage-rail-progress"
                        d="M14 8 V170 l10 14 v62 l-10 14 v100 l10 14 v62 l-10 14 V552"
                        style={{ pathLength: prefersReducedMotion ? (activePreviewIndex + 1) / previewSteps.length : smoothDemoProgress }}
                      />
                    </svg>
                    <motion.span
                      className="demo-stage-rail-dot"
                      style={{ top: prefersReducedMotion ? previewDotTopByStep[activePreviewStep] : demoRailDotTop }}
                    />
                  </div>
                  {previewSteps.map((step) => (
                    <button
                      id={`preview-tab-${step.id}`}
                      key={step.id}
                      type="button"
                      role="tab"
                      aria-label={step.label}
                      aria-selected={activePreviewStep === step.id}
                      className={`demo-step-card ${activePreviewStep === step.id ? "active" : ""}`}
                      onClick={() => handlePreviewStepSelect(step.id)}
                    >
                      <span className="demo-step-meta"><span>{step.number}</span> {step.label}</span>
                      <strong>{step.title}</strong>
                      <span className="demo-step-copy">{step.copy}</span>
                    </button>
                  ))}
                </div>

                <div className="simulator-container">
                  <div className="simulator-header">
                    <span className="simulator-trace-label"><span className="simulator-live-dot" /> Samvid workspace</span>
                    <span className="simulator-step-count">{activePreviewLabel} / 03</span>
                  </div>

                  <div
                    className="simulator-body demo-panel-body"
                    role="tabpanel"
                    aria-labelledby={`preview-tab-${activePreviewStep}`}
                  >
                    <AnimatePresence mode="wait">
                      {activePreviewStep === "intake" && (
                        <motion.div
                          key="intake"
                          className="demo-trace-panel"
                          initial={{ opacity: 0, x: 18, scale: 0.99 }}
                          animate={{ opacity: 1, x: 0, scale: 1 }}
                          exit={{ opacity: 0, x: -14, scale: 0.99 }}
                          transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        >
                          <div className="demo-panel-headline">
                            <span>Email thread · Vendor MSA</span>
                            <span className="success">Samvid copied</span>
                          </div>
                          <div className="preview-email-card">
                            <div className="preview-email-meta">
                              <span className="preview-avatar">PN</span>
                              <div>
                                <strong>Priya Nair</strong>
                                <span>to Alex, procurement@acme.com, samvid.ai</span>
                              </div>
                              <time>09:41 AM</time>
                            </div>
                            <h4>Re: Acme vendor agreement</h4>
                            <p>Can we get this reviewed and ready to send today? Please check renewal, indemnity, and the latest scope changes.</p>
                          </div>
                          <motion.div
                            className="preview-attachment-card"
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 0.12, duration: 0.24 }}
                          >
                            <span className="preview-file-icon"><FileText size={17} /></span>
                            <div>
                              <strong>vendor_agreement_v3.pdf</strong>
                              <span>12 pages · Original thread attached</span>
                            </div>
                            <span className="preview-status-pill processing">Reviewing</span>
                          </motion.div>
                          <div className="preview-samvid-reply">
                            <span className="preview-avatar brand">S</span>
                            <div>
                              <strong>Samvid</strong>
                              <p>Got it. I am reading the whole document and comparing it with the previous version.</p>
                            </div>
                          </div>
                          <div className="demo-message-composer">
                            <span>One email address works the whole thread.</span>
                            <button type="button" aria-label="Continue to review" onClick={() => handlePreviewStepSelect("review")}><ArrowRight size={14} /></button>
                          </div>
                        </motion.div>
                      )}

                      {activePreviewStep === "review" && (
                        <motion.div
                          key="review"
                          className="demo-trace-panel"
                          initial={{ opacity: 0, x: 18, scale: 0.99 }}
                          animate={{ opacity: 1, x: 0, scale: 1 }}
                          exit={{ opacity: 0, x: -14, scale: 0.99 }}
                          transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        >
                          <div className="demo-panel-headline">
                            <span>Review · vendor_agreement_v3.pdf</span>
                            <span className="danger">3 flags</span>
                          </div>
                          <div className="preview-review-summary">
                            <div>
                              <span className="preview-eyebrow">Review complete</span>
                              <h4>Catches what you would miss. Shows you what changed.</h4>
                            </div>
                            <span className="preview-review-score">3<span>flags</span></span>
                          </div>
                          <div className="preview-risk-list">
                            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
                              <span className="preview-risk-level critical">Critical</span>
                              <div>
                                <strong>Uncapped indemnity</strong>
                                <p>You could be responsible for unlimited third-party claims.</p>
                              </div>
                              <span className="preview-page-link">p.14</span>
                            </motion.div>
                            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.14 }}>
                              <span className="preview-risk-level medium">Review</span>
                              <div>
                                <strong>Automatic 12-month renewal</strong>
                                <p>Notice is required 90 days before the renewal date.</p>
                              </div>
                              <span className="preview-page-link">p.8</span>
                            </motion.div>
                            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
                              <span className="preview-risk-level changed">Changed</span>
                              <div>
                                <strong>Scope expanded in v3</strong>
                                <p>Support obligations were added without a fee adjustment.</p>
                              </div>
                              <span className="preview-page-link">Compare</span>
                            </motion.div>
                          </div>
                          <div className="preview-review-actions">
                            <button type="button" className="secondary"><Sparkles size={14} /> Ask about a clause</button>
                            <button type="button" className="primary" onClick={() => handlePreviewStepSelect("track")}>Send for signature <ArrowRight size={14} /></button>
                          </div>
                        </motion.div>
                      )}

                      {activePreviewStep === "track" && (
                        <motion.div
                          key="track"
                          className="demo-trace-panel"
                          initial={{ opacity: 0, x: 18, scale: 0.99 }}
                          animate={{ opacity: 1, x: 0, scale: 1 }}
                          exit={{ opacity: 0, x: -14, scale: 0.99 }}
                          transition={{ type: "spring", stiffness: 300, damping: 30 }}
                        >
                          <div className="demo-panel-headline">
                            <span>Contract board</span>
                            <span className="success">Live</span>
                          </div>
                          <div className="preview-board-progress" aria-label="Contract signing progress">
                            <span className="complete"><Check size={12} /> Ready to send</span>
                            <span className="active"><Clock size={12} /> Out for signature</span>
                            <span>Signed</span>
                          </div>
                          <div className="preview-contract-board-card">
                            <div className="preview-board-card-head">
                              <span className="preview-file-icon"><FileText size={17} /></span>
                              <div><strong>Acme vendor agreement</strong><span>Version 3 · Sent today, 09:02 AM</span></div>
                              <span className="preview-status-pill sent">Out for signature</span>
                            </div>
                            <div className="preview-signer-list">
                              <div><span className="preview-person-dot signed">AN</span><div><strong>Asha Nair</strong><span>Signed at 09:30 AM</span></div><Check size={15} /></div>
                              <div><span className="preview-person-dot viewed">BD</span><div><strong>Bob Davidson</strong><span>Opened 24 minutes ago</span></div><span className="preview-status-copy viewed">Opened</span></div>
                              <div><span className="preview-person-dot">CP</span><div><strong>Charlie Patel</strong><span>No activity yet</span></div><span className="preview-status-copy">Pending</span></div>
                            </div>
                          </div>
                          <motion.div
                            className="preview-nudge-card"
                            initial={{ opacity: 0, y: 8 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: 0.15, duration: 0.24 }}
                          >
                            <Mail size={16} />
                            <div><strong>Follow-up scheduled</strong><span>Charlie gets a nudge in 2 hours if there is no activity.</span></div>
                            <span className="preview-status-pill scheduled">Automatic</span>
                          </motion.div>
                          <div className="preview-renewal-watch"><Clock size={14} /><span>Renewal watch</span><strong>Notice due 15 Sep 2026</strong></div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Core Capabilities Section */}
        <section id="features" className="features-section">
          <div className="section-header">
            <div className="section-kicker">What Samvid does</div>
            <h2 className="section-title">The contract work that should not depend on memory.</h2>
            <p className="section-desc">Samvid turns incoming documents into clear decisions, attributable actions, and a record your team can return to.</p>
          </div>

          <div className="features-grid">
            <div className="feature-card feature-card-anchor">
              <div className="feature-icon-wrapper">
                <Sparkles size={18} />
              </div>
              <h3 className="feature-title">Every risk, tied to evidence</h3>
              <p className="feature-desc">See liability, indemnity, renewal, governing-law, and scope concerns in plain language with the exact supporting text and page.</p>
              <div className="feature-signal">Page-linked findings</div>
            </div>

            <div className="feature-card feature-card-support">
              <div className="feature-icon-wrapper">
                <Cpu size={18} />
              </div>
              <h3 className="feature-title">Scans become review-ready</h3>
              <p className="feature-desc">Image-based and scanned contracts are converted into readable text before analysis, so older documents are not left out of the workflow.</p>
              <div className="feature-signal">Scanned documents supported</div>
            </div>

            <div className="feature-card feature-card-support">
              <div className="feature-icon-wrapper">
                <Mail size={18} />
              </div>
              <h3 className="feature-title">Forward it from your inbox</h3>
              <p className="feature-desc">Send an attachment to your workspace address. Samvid validates, files, parses, and queues the contract without another upload ritual.</p>
              <div className="feature-signal">Forward and review</div>
            </div>

            <div className="feature-card feature-card-base">
              <div className="feature-icon-wrapper">
                <History size={18} />
              </div>
              <h3 className="feature-title">A timeline nobody can rewrite</h3>
              <p className="feature-desc">Signer status changes, actors, notes, timestamps, and IP context remain in an append-only history for clear operational accountability.</p>
              <div className="feature-signal">Complete activity history</div>
            </div>

            <div className="feature-card feature-card-base">
              <div className="feature-icon-wrapper">
                <Layers size={18} />
              </div>
              <h3 className="feature-title">Know which version moved forward</h3>
              <p className="feature-desc">Keep every revision together and pin each signing request to the document snapshot the team actually approved.</p>
              <div className="feature-signal">Approved version linked</div>
            </div>

            <div className="feature-card feature-card-base">
              <div className="feature-icon-wrapper">
                <Clock size={18} />
              </div>
              <h3 className="feature-title">Never lose the next step</h3>
              <p className="feature-desc">Keep renewal dates, notice windows, approval states, and signer follow-ups visible so important contract work does not quietly stall.</p>
              <div className="feature-signal">Deadlines and next actions</div>
            </div>
          </div>
        </section>

        <section id="changelog" className="changelog-section">
          <div className="changelog-label">
            <span>Changelog</span>
            <time dateTime="2026-07">July 2026</time>
          </div>
          <div className="changelog-copy">
            <h2>Samvid workspace is now live.</h2>
            <p>AI-assisted contract review, email delivery, document history, and immutable signer-status tracking are available in one workspace.</p>
          </div>
          <Link to="/changelog" className="changelog-link">
            View changelog <ArrowRight size={14} />
          </Link>
        </section>

        {/* Workflow Section */}
        <section id="workflow" className="workflow-section">
          <div className="section-header">
            <div className="section-kicker">How it works</div>
            <h2 className="section-title">One contract in. A decision-ready record out.</h2>
            <p className="section-desc">Samvid keeps the document, the reasoning, and the next action connected through every stage.</p>
          </div>

          <div className="workflow-grid">
            <div className="workflow-col">
              <div className="workflow-num">01 / FORWARD</div>
              <h3 className="workflow-title">Send the contract</h3>
              <p className="workflow-desc">
                Upload a PDF, DOCX, or TXT file, or forward the attachment from the email thread where the work already started.
              </p>
            </div>
            <div className="workflow-col">
              <div className="workflow-num">02 / REVIEW</div>
              <h3 className="workflow-title">Understand what matters</h3>
              <p className="workflow-desc">
                Samvid reads the full document, extracts the key terms, and explains each material risk with evidence you can verify.
              </p>
            </div>
            <div className="workflow-col">
              <div className="workflow-num">03 / TRACK</div>
              <h3 className="workflow-title">Keep the handoff moving</h3>
              <p className="workflow-desc">
                Coordinate review and manually track signer progress while every status update becomes part of the audit history.
              </p>
            </div>
            <div className="workflow-col">
              <div className="workflow-num">04 / RECALL</div>
              <h3 className="workflow-title">Return to the answer</h3>
              <p className="workflow-desc">
                Find the approved version, the important clause, the signer state, and the decision context without reopening old threads.
              </p>
            </div>
          </div>
        </section>

        <section className="memory-section" aria-labelledby="memory-title">
          <div className="memory-copy">
            <div className="section-kicker">Contract memory</div>
            <h2 id="memory-title">Keep the next question answerable.</h2>
            <p>Samvid keeps terms, risks, evidence, versions, and signer events connected to the contract record, so your team can return to the source instead of restarting the review.</p>
            <Link to="/chats" className="memory-link">
              Explore the workspace <ArrowRight size={14} />
            </Link>
          </div>
          <div className="memory-console" aria-label="Questions retained contract records can answer">
            <div className="memory-console-heading">
              <Search size={16} /> Questions your records keep answerable
            </div>
            <div className="memory-question">Which agreements renew in the next 90 days?</div>
            <div className="memory-question">Where do we have uncapped liability?</div>
            <div className="memory-question">Who is still waiting to sign?</div>
            <div className="memory-question">What changed in the latest vendor draft?</div>
          </div>
        </section>

        <section className="closing-cta">
          <div>
            <div className="section-kicker">Start with the next contract</div>
            <h2>Give every handoff a record.</h2>
            <p>Bring review, evidence, versions, and signer status into one workspace your team can trust.</p>
          </div>
          <div className="closing-cta-actions">
            <a href="#workflow" className="btn-lp-secondary">See the workflow</a>
            <Link to="/chats" className="btn-lp-primary">Open workspace <ArrowRight size={15} /></Link>
          </div>
        </section>

        {/* Disclaimer Banner */}
        <section id="disclaimer" className="disclaimer-banner">
          <AlertTriangle className="disclaimer-icon" size={20} />
          <div className="disclaimer-text">
            <strong>Signing status tracking only:</strong> Samvid coordinates and records the signing workflow. It does not place signature fields, verify legal identity, issue digital certificates, or execute legally binding electronic signatures.
          </div>
        </section>

        {/* Footer */}
        <footer className="landing-footer">
          <h2 className="footer-punchline">
            <span className="footer-punchline-pixel">Workspace</span> to fix your chaos with <span className="footer-punchline-brand">samvid.ai</span>
          </h2>

          <div className="footer-details">
            <div className="footer-logo-row">
              <div className="landing-logo" style={{ width: "28px", height: "28px", fontSize: "13px" }}>S</div>
              <span style={{ fontWeight: 700, fontSize: "15px", letterSpacing: 0 }}>Samvid</span>
            </div>
            <div className="footer-copy">
              &copy; {new Date().getFullYear()} Samvid. All rights reserved. Built for modern legal and procurement workflows.
            </div>

            <div className="tech-stack-label">Built with Chaos in <span className="tech-stack-location">Bengaluru</span></div>
          </div>
        </footer>
      </div>
    </div>
  );
}
