import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import {
  FileText,
  Mail,
  Layers,
  Lock,
  ShieldAlert,
  Clock,
  ArrowRight,
  Sparkles,
  UploadCloud,
  Check,
  RotateCcw,
  Cpu,
  History,
  Terminal,
  AlertTriangle,
  ChevronRight,
  ExternalLink
} from "lucide-react";
import "./home.css";

type TabType = "review" | "email" | "timeline";
const MotionLink = motion.create(Link);

export function LandingPage() {
  const [activeTab, setActiveTab] = useState<TabType>("review");
  const [isPlaying, setIsPlaying] = useState(true);
  const [isPastHero, setIsPastHero] = useState(false);
  const [navShift, setNavShift] = useState(0);
  const [edgeShift, setEdgeShift] = useState(0);
  const heroRef = useRef<HTMLElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const navCtaRef = useRef<HTMLDivElement>(null);
  const prefersReducedMotion = useReducedMotion();
  const { scrollY } = useScroll();
  const navX = useTransform(scrollY, [0, 320], [0, navShift]);
  const brandX = useTransform(scrollY, [0, 320], [0, -edgeShift]);
  const ctaX = useTransform(scrollY, [0, 320], [0, edgeShift]);
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
      const isCompact = window.matchMedia("(max-width: 860px)").matches;
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

  // Tab 1: AI Review simulation states
  const [aiProgress, setAiProgress] = useState(0);
  const [aiStep, setAiStep] = useState(0); // 0: Idle, 1: Uploading, 2: OCR, 3: OpenAI analysis, 4: Done

  // Tab 2: Email simulation states
  const [consoleLogs, setConsoleLogs] = useState<Array<{ text: string; type: "input" | "success" | "warning" | "muted" }>>([]);
  const [emailStep, setEmailStep] = useState(0);

  // Tab 3: Timeline simulation states
  const [timelineStep, setTimelineStep] = useState(0);

  // Handle AI Review Simulation loop
  useEffect(() => {
    if (activeTab !== "review" || !isPlaying) return;

    setAiStep(1);
    setAiProgress(0);

    const uploadInterval = setInterval(() => {
      setAiProgress((prev) => {
        if (prev >= 100) {
          clearInterval(uploadInterval);
          setAiStep(2);
          return 100;
        }
        return prev + 5;
      });
    }, 100);

    return () => clearInterval(uploadInterval);
  }, [activeTab, isPlaying, aiStep === 0]);

  useEffect(() => {
    if (activeTab !== "review" || !isPlaying) return;

    let timer: any;
    if (aiStep === 2) {
      // OCR step
      timer = setTimeout(() => {
        setAiStep(3);
      }, 1500);
    } else if (aiStep === 3) {
      // AI analysis step
      timer = setTimeout(() => {
        setAiStep(4);
      }, 2000);
    }

    return () => clearTimeout(timer);
  }, [aiStep, activeTab, isPlaying]);

  // Handle Email Simulation loop
  const emailLogs = [
    { text: "[09:41:02] Inbound email detected on Resend SMTP server...", type: "muted" as const },
    { text: "[09:41:03] Sender validated: legal@acmedynamics.com", type: "success" as const },
    { text: "[09:41:03] Extracting attachment: 'intervue_services_agreement.pdf' (14.4 KB)", type: "input" as const },
    { text: "[09:41:04] Dispatching webhook email.received (ID: wh_resend_9b821a)", type: "muted" as const },
    { text: "[09:41:05] Triggering Sarvam OCR engine (extracting scanned layers)...", type: "input" as const },
    { text: "[09:41:07] Running contract intelligence engine (OpenAI structured output)...", type: "input" as const },
    { text: "[09:41:08] Extraction completed successfully:", type: "success" as const },
    { text: "  ↳ Parties: Asha Corp (Provider) & Acme Dynamics (Client)", type: "success" as const },
    { text: "  ↳ Found 1 high-severity risk: Unlimited Indemnification (Page 14)", type: "warning" as const },
    { text: "[09:41:09] Saving audit-trail & initial signing status (pending)", type: "muted" as const },
    { text: "[09:41:10] Resending review scorecard to legal@acmedynamics.com...", type: "input" as const },
    { text: "[09:41:11] Email webhook pipeline execution complete.", type: "success" as const }
  ];

  useEffect(() => {
    if (activeTab !== "email" || !isPlaying) return;

    setConsoleLogs([]);
    setEmailStep(0);

    const interval = setInterval(() => {
      setEmailStep((prev) => {
        if (prev >= emailLogs.length - 1) {
          clearInterval(interval);
          return prev;
        }
        return prev + 1;
      });
    }, 800);

    return () => clearInterval(interval);
  }, [activeTab, isPlaying]);

  useEffect(() => {
    if (activeTab === "email" && isPlaying) {
      setConsoleLogs(emailLogs.slice(0, emailStep + 1));
    }
  }, [emailStep, activeTab, isPlaying]);

  // Handle Timeline simulation loop
  useEffect(() => {
    if (activeTab !== "timeline" || !isPlaying) return;

    setTimelineStep(0);
    const interval = setInterval(() => {
      setTimelineStep((prev) => {
        if (prev >= 3) {
          clearInterval(interval);
          return 3;
        }
        return prev + 1;
      });
    }, 1500);

    return () => clearInterval(interval);
  }, [activeTab, isPlaying]);

  const restartSimulation = () => {
    setIsPlaying(false);
    setTimeout(() => {
      setAiStep(0);
      setEmailStep(0);
      setTimelineStep(0);
      setConsoleLogs([]);
      setIsPlaying(true);
    }, 50);
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
            <Link to="/changelog" className="landing-nav-link">Changelog</Link>
            <a href="#features" className="landing-nav-link">Features</a>
          </motion.nav>
          <motion.div
            ref={navCtaRef}
            className="landing-nav-cta"
            style={{ x: prefersReducedMotion ? 0 : smoothCtaX }}
          >
            <Link to="/contracts" className="btn-lp-secondary">
              Sign up
            </Link>
            <a href="#demo" className="btn-lp-primary">Book a Demo</a>
          </motion.div>
        </header>

        {/* Hero Section */}
        <section ref={heroRef} className="hero-section">
          <div className="hero-content-wrapper">
            <div className="hero-badge">
              AI TEAMMATE FOR LEGAL & PROCUREMENT
            </div>
            <h1 className="hero-heading">
              <span className="hero-heading-dial">
                <span className="hero-dial-word">review. </span>
                <span className="hero-dial-word">sign. </span>
                <span className="hero-dial-word hero-heading-highlight">verify. </span>
              </span>
            </h1>
            <p className="hero-subheading">
              Review contracts, flag risks, track approvals, and coordinate next steps directly from{" "}
              <span className="hero-channel-flip" aria-label="Gmail and Slack">
                <span className="hero-channel-flip-track" aria-hidden="true">
                  <span className="hero-channel-face hero-channel-front">
                    <img src="/gmail.webp" alt="Gmail" />
                  </span>
                  <span className="hero-channel-face hero-channel-back">
                    <img src="https://upload.wikimedia.org/wikipedia/commons/d/d5/Slack_icon_2019.svg" alt="Slack" />
                  </span>
                </span>
              </span>{" "}
              with an AI teammate built for faster contract execution.
            </p>
            <div className="hero-actions">
              <a href="#features" className="btn-lp-secondary">
                Book a Demo
              </a>
              <Link to="/contracts" className="btn-lp-primary">
                Open Workspace <ArrowRight size={15} />
              </Link>
              
            </div>
          </div>
          <div className="hero-road" aria-hidden="true">
            <img src="/road-tuktuk-bike.webp" alt="" />
          </div>
        </section>

        {/* Interactive Workspace Simulator
        <section id="demo" className="demo-section" aria-label="Interactive workspace demo">
          <div className="simulator-container">
            <div className="simulator-header">
              <div className="simulator-dots">
                <div className="simulator-dot"></div>
                <div className="simulator-dot"></div>
                <div className="simulator-dot"></div>
              </div>
              <div className="simulator-tabs">
                <button
                  className={`simulator-tab ${activeTab === "review" ? "active" : ""}`}
                  onClick={() => { setActiveTab("review"); restartSimulation(); }}
                >
                  <Sparkles size={14} /> AI Review
                </button>
                <button
                  className={`simulator-tab ${activeTab === "email" ? "active" : ""}`}
                  onClick={() => { setActiveTab("email"); restartSimulation(); }}
                >
                  <Mail size={14} /> Email Webhook
                </button>
                <button
                  className={`simulator-tab ${activeTab === "timeline" ? "active" : ""}`}
                  onClick={() => { setActiveTab("timeline"); restartSimulation(); }}
                >
                  <History size={14} /> Signer Timeline
                </button>
              </div>
              <button 
                onClick={restartSimulation}
                className="btn-lp-secondary" 
                style={{ padding: "4px 8px", minHeight: "28px", fontSize: "11px" }}
                title="Restart simulation"
              >
                <RotateCcw size={12} /> Reset
              </button>
            </div>

            <div className="simulator-body">
           
              {activeTab === "review" && (
                <div className="ai-sim-grid">
                  <div className="ai-sim-sidebar">
                    <div className="ai-sim-doc-info">
                      <div className="doc-name">
                        <FileText size={15} className="text-teal" style={{ color: "#14b8a6" }} />
                        vendor_agreement.pdf
                      </div>
                      <div className="doc-meta">PDF · 12 Pages · 244 KB</div>
                    </div>
                    <div className="ai-sim-pipeline">
                      <div className={`pipeline-step ${aiStep >= 1 ? (aiStep === 1 ? "active" : "completed") : ""}`}>
                        <div className="step-indicator">
                          {aiStep > 1 ? <Check size={10} /> : "1"}
                        </div>
                        <span>Upload File</span>
                      </div>
                      {aiStep === 1 && (
                        <div className="ai-sim-progress-track">
                          <div className="ai-sim-progress-bar" style={{ width: `${aiProgress}%` }}></div>
                        </div>
                      )}

                      <div className={`pipeline-step ${aiStep >= 2 ? (aiStep === 2 ? "active" : "completed") : ""}`}>
                        <div className="step-indicator">
                          {aiStep > 2 ? <Check size={10} /> : "2"}
                        </div>
                        <span>Sarvam OCR Scan</span>
                      </div>

                      <div className={`pipeline-step ${aiStep >= 3 ? (aiStep === 3 ? "active" : "completed") : ""}`}>
                        <div className="step-indicator">
                          {aiStep > 3 ? <Check size={10} /> : "3"}
                        </div>
                        <span>OpenAI Term Extraction</span>
                      </div>

                      <div className={`pipeline-step ${aiStep >= 4 ? "completed" : ""}`}>
                        <div className="step-indicator">
                          {aiStep >= 4 ? <Check size={10} /> : "4"}
                        </div>
                        <span>Risk Scorecard Ready</span>
                      </div>
                    </div>
                  </div>

                  <div className="ai-sim-output-container">
                    {aiStep < 4 ? (
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--lp-text-secondary)", gap: "12px" }}>
                        <Cpu className="spin" size={24} style={{ animation: "spin 2s linear infinite", color: "#14b8a6" }} />
                        <span style={{ fontFamily: "var(--lp-font-mono)", fontSize: "12px" }}>
                          {aiStep === 1 && "Uploading document..."}
                          {aiStep === 2 && "Sarvam OCR engine processing pages..."}
                          {aiStep === 3 && "Analyzing contract clauses with OpenAI..."}
                        </span>
                      </div>
                    ) : (
                      <div className="ai-sim-output">
                        <div className="sim-output-header">
                          <div className="sim-output-title">Review Scorecard</div>
                          <span className="sim-badge" style={{ color: "#34d399", background: "rgba(52,211,153,0.1)", border: "1px solid rgba(52,211,153,0.2)" }}>Review Ready</span>
                        </div>
                        
                        <div className="sim-summary-grid">
                          <div className="sim-summary-card">
                            <div className="sim-summary-label">Contract Type</div>
                            <div className="sim-summary-value">Vendor Agreement</div>
                          </div>
                          <div className="sim-summary-card">
                            <div className="sim-summary-label">Primary Party</div>
                            <div className="sim-summary-value">Acme Dynamics</div>
                          </div>
                          <div className="sim-summary-card">
                            <div className="sim-summary-label">Counterparty</div>
                            <div className="sim-summary-value">Asha Corp</div>
                          </div>
                        </div>

                        <div className="sim-risk-item">
                          <div className="sim-risk-header">
                            <div className="sim-risk-title">Unlimited Indemnification Clause</div>
                            <span className="sim-badge red">Critical</span>
                          </div>
                          <div className="sim-risk-desc">
                            The provider indemnifies the customer without any liability cap. This creates asymmetric operational exposure.
                          </div>
                          <blockquote className="sim-risk-quote">
                            Page 14: "...Provider shall defend, indemnify, and hold harmless Customer... from any and all damages without limitation."
                          </blockquote>
                        </div>

                        <div className="sim-risk-item">
                          <div className="sim-risk-header">
                            <div className="sim-risk-title">Automatic 12-Month Renewal</div>
                            <span className="sim-badge amber">Medium</span>
                          </div>
                          <div className="sim-risk-desc">
                            The agreement automatically renews for successive 12-month periods unless written notice is given 90 days prior.
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              // Tab 2: Email Webhook Simulator 
              {activeTab === "email" && (
                <div className="email-sim-layout">
                  <div className="email-flow-visual">
                    <div className={`flow-node ${emailStep >= 0 ? "active" : ""}`}>
                      <div className="flow-icon-circle"><Mail size={18} /></div>
                      <span className="flow-node-title">Inbound Email</span>
                      <span className="flow-node-desc">contracts@oldimeluub...</span>
                    </div>

                    <div className="flow-connector"></div>

                    <div className={`flow-node ${emailStep >= 3 ? "active" : ""}`}>
                      <div className="flow-icon-circle"><Terminal size={18} /></div>
                      <span className="flow-node-title">Webhook Adapter</span>
                      <span className="flow-node-desc">Resend HTTP Event</span>
                    </div>

                    <div className="flow-connector"></div>

                    <div className={`flow-node ${emailStep >= 6 ? "active" : ""}`}>
                      <div className="flow-icon-circle"><Sparkles size={18} /></div>
                      <span className="flow-node-title">Samvid Core</span>
                      <span className="flow-node-desc">OCR + AI Pipeline</span>
                    </div>
                  </div>

                  <div className="email-sim-console">
                    {consoleLogs.map((log, i) => (
                      <div key={i} className={`console-line ${log.type}`}>
                        {log.text}
                      </div>
                    ))}
                    {isPlaying && emailStep < emailLogs.length - 1 && (
                      <div className="console-line input" style={{ display: "inline-block", width: "8px", height: "12px", background: "var(--lp-text-primary)", marginLeft: "2px", animation: "blink 1s step-end infinite" }}></div>
                    )}
                  </div>
                </div>
              )}

              // Tab 3: Signer Timeline Simulator 
              {activeTab === "timeline" && (
                <div className="timeline-sim-layout">
                  <div className="timeline-signer-card">
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", fontWeight: "600", color: "var(--lp-text-primary)", borderBottom: "1px solid var(--lp-border)", paddingBottom: "8px" }}>
                      <span>Signer Status</span>
                      <span style={{ fontFamily: "var(--lp-font-mono)", color: "var(--lp-teal)" }}>Version v1.2</span>
                    </div>
                    <div className="timeline-signer-row">
                      <div className="signer-info-sim">
                        <span className="signer-name-sim">Asha Nair</span>
                        <span className="signer-email-sim">asha@ashacorp.com</span>
                      </div>
                      <span className="sim-badge" style={{ color: "#34d399", background: "rgba(52,211,153,0.1)", border: "1px solid rgba(52,211,153,0.2)" }}>Signed</span>
                    </div>
                    <div className="timeline-signer-row">
                      <div className="signer-info-sim">
                        <span className="signer-name-sim">Bob Davidson</span>
                        <span className="signer-email-sim">bob@acmedynamics.com</span>
                      </div>
                      <span className="sim-badge" style={{ color: "#fbbf24", background: "rgba(251,191,36,0.1)", border: "1px solid rgba(251,191,36,0.2)" }}>Viewed</span>
                    </div>
                    <div className="timeline-signer-row">
                      <div className="signer-info-sim">
                        <span className="signer-name-sim">Charlie Patel</span>
                        <span className="signer-email-sim">charlie@acmedynamics.com</span>
                      </div>
                      <span className="sim-badge" style={{ color: "var(--lp-text-muted)", background: "rgba(255,255,255,0.02)", border: "1px solid var(--lp-border)" }}>Pending</span>
                    </div>
                  </div>

                  <div className="timeline-flow-col">
                    <div className={`timeline-event-sim ${timelineStep >= 0 ? "active" : ""}`}>
                      <div className="timeline-event-dot"></div>
                      <div className="event-actor">
                        <span>Signing Request Initialized</span>
                        <span style={{ fontSize: "10px", color: "var(--lp-text-muted)", fontWeight: "normal" }}>Yesterday · 05:40 PM</span>
                      </div>
                      <div className="event-details">Request created by admin@samvid.ai, pinned to version v1.2.</div>
                    </div>

                    <div className={`timeline-event-sim ${timelineStep >= 1 ? "active" : ""}`}>
                      <div className="timeline-event-dot"></div>
                      <div className="event-actor">
                        <span>Asha Nair viewed contract</span>
                        <span style={{ fontSize: "10px", color: "var(--lp-text-muted)", fontWeight: "normal" }}>Today · 09:12 AM</span>
                      </div>
                      <div className="event-details">IP address logged: 198.51.100.42.</div>
                    </div>

                    <div className={`timeline-event-sim ${timelineStep >= 2 ? "active" : ""}`}>
                      <div className="timeline-event-dot"></div>
                      <div className="event-actor">
                        <span>Asha Nair signed contract</span>
                        <span style={{ fontSize: "10px", color: "var(--lp-text-muted)", fontWeight: "normal" }}>Today · 09:30 AM</span>
                      </div>
                      <div className="event-details">Status transitioned to 'Signed'. Immutable audit record logged.</div>
                      <div className="event-note">"Approved via legal committee check"</div>
                    </div>

                    <div className={`timeline-event-sim ${timelineStep >= 3 ? "active" : ""}`}>
                      <div className="timeline-event-dot"></div>
                      <div className="event-actor">
                        <span>Bob Davidson viewed contract</span>
                        <span style={{ fontSize: "10px", color: "var(--lp-text-muted)", fontWeight: "normal" }}>Today · 09:41 AM</span>
                      </div>
                      <div className="event-details">IP address logged: 198.51.100.77. Status changed to 'Viewed'.</div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section> */}

        {/* Core Capabilities Section */}
        <section id="features" className="features-section">
          <div className="section-header">
            <h2 className="section-title">Contract intelligence engineered for speed.</h2>
            <p className="section-desc">Samvid reduces review delays and aligns stakeholders without the heavy overhead of legacy contract lifecycle managers.</p>
          </div>

          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <Sparkles size={18} />
              </div>
              <h3 className="feature-title">AI-Powered Clause Analysis</h3>
              <p className="feature-desc">Leverages structured OpenAI contract intelligence output to extract parties, parameters, renewal terms, and critical next steps instantly.</p>
            </div>

            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <Cpu size={18} />
              </div>
              <h3 className="feature-title">Advanced Sarvam OCR</h3>
              <p className="feature-desc">No more manual transcriptions. Scanned contracts and images are automatically normalized using high-fidelity Sarvam OCR pipelines.</p>
            </div>

            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <Mail size={18} />
              </div>
              <h3 className="feature-title">Inbound Email Pipeline</h3>
              <p className="feature-desc">Directly route documents by forwarding them to your workspace address. Incoming contracts are parsed, scored, and filed automatically.</p>
            </div>

            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <History size={18} />
              </div>
              <h3 className="feature-title">Immutable Audit Trails</h3>
              <p className="feature-desc">Preserve every signer action, IP address log, status transition, and manual update in a secured, read-only event timeline.</p>
            </div>

            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <Layers size={18} />
              </div>
              <h3 className="feature-title">Version Management</h3>
              <p className="feature-desc">Upload revisions and track multiple iterations of a draft. Securely pin active signing requests to specific historical snapshots.</p>
            </div>

            <div className="feature-card">
              <div className="feature-icon-wrapper">
                <Lock size={18} />
              </div>
              <h3 className="feature-title">Local-First Architecture</h3>
              <p className="feature-desc">Designed with SQLite for light local setups and clean PostgreSQL integrations for enterprise-grade production infrastructure.</p>
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
            <h2 className="section-title">The Three-Stage Lifecycle</h2>
            <p className="section-desc">How Samvid automates contract reviews and signing statuses from upload to archive.</p>
          </div>

          <div className="workflow-grid">
            <div className="workflow-col">
              <div className="workflow-num">01 / INGEST</div>
              <h3 className="workflow-title">Submit Contracts</h3>
              <p className="workflow-desc">
                Drag-and-drop contracts (PDF, DOCX, TXT) via the browser console or simply forward them to your workspace email inbox for webhook ingestion.
              </p>
            </div>
            <div className="workflow-col">
              <div className="workflow-num">02 / EXTRACT</div>
              <h3 className="workflow-title">Identify Risks</h3>
              <p className="workflow-desc">
                The platform runs OCR processing and structured LLM extraction to identify liabilities, indemnities, governing law, and parties with evidence-grounded page links.
              </p>
            </div>
            <div className="workflow-col">
              <div className="workflow-num">03 / TRACK</div>
              <h3 className="workflow-title">Monitor Signatures</h3>
              <p className="workflow-desc">
                Orchestrate review statuses and manually track signers' actions. Every status change creates a secure timeline event in your audit ledger.
              </p>
            </div>
          </div>
        </section>

        {/* Disclaimer Banner */}
        <section id="disclaimer" className="disclaimer-banner">
          <AlertTriangle className="disclaimer-icon" size={20} />
          <div className="disclaimer-text">
            <strong>Signing Status Tracking Only:</strong> Samvid provides signature workflow coordination. It does not place visual signature fields directly onto documents, verify signer legal identity, generate digital signature certificates, or execute legally binding electronic signatures. A future integration with e-signature providers (e.g. DocuSign, Adobe Sign) is required for execution.
          </div>
        </section>

        {/* Footer */}
        <footer className="landing-footer">
          <div className="footer-logo-row">
            <div className="landing-logo" style={{ width: "28px", height: "28px", fontSize: "13px" }}>S</div>
            <span style={{ fontWeight: 700, fontSize: "15px", letterSpacing: 0 }}>Samvid</span>
          </div>
          <div className="footer-copy">
            &copy; {new Date().getFullYear()} Samvid. All rights reserved. Built for modern legal and procurement workflows.
          </div>
          
          <div className="tech-stack-label">Under the Hood</div>
          <div className="tech-stack-tags">
            <span className="tech-tag">React / TypeScript</span>
            <span className="tech-tag">FastAPI</span>
            <span className="tech-tag">OpenAI API</span>
            <span className="tech-tag">Sarvam OCR</span>
            <span className="tech-tag">Resend SMTP</span>
            <span className="tech-tag">SQLite / PostgreSQL</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
