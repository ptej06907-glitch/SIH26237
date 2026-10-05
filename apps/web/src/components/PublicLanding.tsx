"use client";

import { useEffect, useRef } from "react";
import {
  ArrowDown, ArrowRight, ArrowUpRight, Check, CircleAlert, Database,
  FileCheck2, FileKey2, FileSearch, FileText, Fingerprint, KeyRound,
  LockKeyhole, ScanSearch, ShieldCheck, ShieldHalf, Users,
} from "lucide-react";
import styles from "./PublicLanding.module.css";

type Props = {
  loginUser: string;
  setLoginUser: (value: string) => void;
  loginPassword: string;
  setLoginPassword: (value: string) => void;
  loginError: string;
  loginBusy: boolean;
  onSignIn: () => void;
};

const photoCredits = {
  sender: { label: "Indian Air Force · LCA Tejas", source: "https://www.pib.gov.in/Pressreleaseshare.aspx?PRID=1936373" },
  recipient: { label: "Indian Navy · Indigenous aircraft carrier Vikrant", source: "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1845871" },
  investigator: { label: "Indian Army · Republic Day rehearsal, Kartavya Path", source: "https://www.pib.gov.in/ShowAlbum.aspx?albumid=186928" },
  auditor: { label: "Republic Day rehearsal · Kartavya Path, New Delhi", source: "https://www.pib.gov.in/ShowAlbum.aspx?albumid=186928" },
};

const roles = [
  { id: "sender", number: "01", label: "Document Authority", icon: FileKey2,
    account: "sender", action: "Sign in as sender", title: "Secure the source.", accent: "Choose who may open it.",
    description: "Upload a synthetic PDF, select recipients and prepare one encrypted document with a separate post-quantum key envelope for each person.",
    tasks: ["Upload and classify a PDF", "Authorize selected recipients", "Distribute one encrypted document"],
    next: "recipient", nextLabel: "Recipient" },
  { id: "recipient", number: "02", label: "Recipient", icon: Users,
    account: "REC-002", action: "Sign in as recipient", title: "Open your copy.", accent: "Leave a verifiable trace.",
    description: "See only documents addressed to your account. Every decryption creates a fresh visual watermark and signed ledger event before the PDF is released.",
    tasks: ["View only addressed documents", "Decrypt with your ML-KEM identity", "Download a uniquely marked PDF"],
    next: "investigator", nextLabel: "Investigator" },
  { id: "investigator", number: "03", label: "Forensic Investigator", icon: FileSearch,
    account: "investigator", action: "Sign in as investigator", title: "A PDF is found.", accent: "Follow the evidence.",
    description: "Upload a suspected copy. The detector reads rendered page content, seeks its watermark and independently checks the recipient signature and ledger.",
    tasks: ["Analyze a found PDF", "Review watermark correlation and session", "Export a technical evidence report"],
    next: "auditor", nextLabel: "Auditor" },
  { id: "auditor", number: "04", label: "Auditor", icon: ShieldHalf,
    account: "auditor", action: "Sign in as auditor", title: "Trust the checks.", accent: "Inspect the chain.",
    description: "Review signed decryption events and three local validator replicas. Verify the chain and demonstrate how one corrupted replica is rejected.",
    tasks: ["Inspect blocks and signed events", "Re-run chain and quorum verification", "Run the safe demo tamper test"],
    next: "access", nextLabel: "Sign in" },
] as const;

function RolePreview({ role }: { role: typeof roles[number]["id"] }) {
  return <div className={styles.preview} aria-label={`${role} workflow illustration`}>
    <div className={styles.previewOverline}>WORKSPACE PREVIEW / {role.toUpperCase()}</div>
    {role === "sender" && <><div className={styles.previewDoc}><FileText size={23}/><div><strong>Source document</strong><small>One encrypted PDF</small></div><LockKeyhole size={17}/></div><div className={styles.previewLine}/><div className={styles.previewStack}>{["REC-001", "REC-002", "REC-003"].map(id => <div key={id}><KeyRound size={17}/><strong>{id}</strong><span>ML-KEM envelope</span></div>)}</div><p>ONE CIPHERTEXT <b>→</b> THREE RECIPIENT ENVELOPES</p></>}
    {role === "recipient" && <><div className={styles.navyPhoto} role="img" aria-label="Indian Navy indigenous aircraft carrier Vikrant, photograph from PIB"/><div className={styles.previewHeader}><span><LockKeyhole size={17}/> MY DOCUMENTS</span><span>REC-002</span></div><div className={styles.previewDoc}><FileText size={23}/><div><strong>Authorized PDF</strong><small>Available through your own envelope</small></div><span>01</span></div><div className={styles.previewSteps}><span><KeyRound size={18}/> Decrypt</span><ArrowRight size={16}/><span><Fingerprint size={18}/> Mark</span><ArrowRight size={16}/><span><FileCheck2 size={18}/> Sign</span></div><p>A NEW SESSION IS CREATED FOR EVERY ACCESS</p></>}
    {role === "investigator" && <><div className={styles.previewDrop}><ScanSearch size={34}/><strong>Suspected PDF</strong><span>Analyze rendered visual content</span></div><div className={styles.previewChecks}><span>01 <b>Watermark signal</b> → Session match</span><span>02 <b>Recipient signature</b> → ML-DSA check</span><span>03 <b>Ledger chain</b> → Quorum check</span></div><p>AMBIGUOUS SIGNALS RETURN INCONCLUSIVE</p></>}
    {role === "auditor" && <><div className={styles.previewDoc}><Database size={23}/><div><strong>Hash-linked event block</strong><small>Signed decryption + validator approvals</small></div></div><div className={styles.previewStack}>{["Validator 1", "Validator 2", "Validator 3"].map((name, index) => <div key={name}><span className={styles.nodeNumber}>0{index + 1}</span><strong>{name}</strong><span>LOCAL STORE</span></div>)}</div><p>COMMIT REQUIRES 2 OF 3 VALID APPROVALS</p></>}
  </div>;
}

const HOSTED_DEMO = process.env.NEXT_PUBLIC_API_URL === "/api";

export default function PublicLanding({ loginUser, setLoginUser, loginPassword, setLoginPassword, loginError, loginBusy, onSignIn }: Props) {
  const passwordRef = useRef<HTMLInputElement>(null);
  const pageRef = useRef<HTMLDivElement>(null);
  const progressRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const page = pageRef.current;
    if (!page) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const scenes = [...page.querySelectorAll<HTMLElement>("[data-scene]")];
    let observer: IntersectionObserver | undefined;
    if (!reducedMotion) {
      page.dataset.motion = "on";
      observer = new IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) {
          (entry.target as HTMLElement).dataset.visible = "true";
          observer?.unobserve(entry.target);
        }
      }, { threshold: 0.12, rootMargin: "0px 0px -30px 0px" });
      page.querySelectorAll("[data-reveal]").forEach(element => observer?.observe(element));
    }
    let frame = 0;
    const paint = () => {
      const height = document.documentElement.scrollHeight - window.innerHeight;
      progressRef.current?.style.setProperty("--scroll-progress", String(height > 0 ? window.scrollY / height : 0));
      if (!reducedMotion) for (const scene of scenes) {
        const rect = scene.getBoundingClientRect();
        if (rect.bottom > 0 && rect.top < window.innerHeight) {
          const distance = (rect.top + rect.height / 2 - window.innerHeight / 2) / window.innerHeight;
          scene.style.setProperty("--scene-shift", `${Math.max(-28, Math.min(28, -distance * 20))}px`);
        }
      }
      frame = 0;
    };
    const onScroll = () => { if (!frame) frame = window.requestAnimationFrame(paint); };
    paint();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => { observer?.disconnect(); window.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); if (frame) window.cancelAnimationFrame(frame); };
  }, []);
  const choose = (account: string) => {
    setLoginUser(account);
    setLoginPassword("");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById("access")?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    window.setTimeout(() => passwordRef.current?.focus({ preventScroll: true }), reducedMotion ? 0 : 450);
  };

  return <div ref={pageRef} className={styles.page}>
    <div className={styles.intro} aria-hidden="true"><span className={styles.introWord}>Source<span>X</span></span><i/></div>
    <div ref={progressRef} className={styles.scrollProgress} aria-hidden="true"/>
    <a className={styles.skip} href="#main">Skip to main content</a>
    <div className={styles.utility}><div className={styles.wrap}><span>SIH 2026 <b>•</b> Ministry of Defence problem statement</span><span>{HOSTED_DEMO ? "HOSTED RESEARCH DEMO" : "LOCAL RESEARCH PROTOTYPE"}</span></div></div>
    <header className={styles.header}><div className={styles.wrap}>
      <a href="#top" className={styles.brand} aria-label="SourceX, top of page"><span className={styles.brandMark}><ShieldCheck size={22}/></span><span><strong>SourceX</strong><small>SIH26237 DEMONSTRATOR</small></span></a>
      <nav aria-label="Landing page navigation"><a href="#journey">How it works</a><a href="#roles">Explore roles</a><button type="button" onClick={() => choose("sender")}>Enter workspace <ArrowUpRight size={16}/></button></nav>
    </div></header>
    <div className={styles.warning}><div className={styles.wrap}><CircleAlert size={15}/> SIH 2026 Prototype — Not an official Ministry of Defence deployment. Synthetic documents only.</div></div>

    <main id="main">
      <section id="top" className={styles.hero}><div className={`${styles.wrap} ${styles.heroGrid}`}>
        <div className={styles.heroCopy}><span className={styles.lightKicker}><i/> INDIAN DEFENCE · SECURE DOCUMENT PROVENANCE</span><h1 className={styles.sourceTitle}>Source<span>X</span></h1><h2 className={styles.heroStatement}>Every document has a journey.<br/><em>Every copy leaves evidence.</em></h2><p>One PDF is encrypted once. Authorized recipients open their own copies. A subtle visual watermark links each decryption to a signed event on a local, tamper-evident ledger.</p><div className={styles.heroActions}><a href="#roles" className={styles.heroPrimary}>Explore the four roles <ArrowDown size={17}/></a><button type="button" onClick={() => choose("sender")}>Sign in to the demo <ArrowRight size={17}/></button></div><div className={styles.heroFacts}><span><Check size={15}/> Post-quantum key establishment</span><span><Check size={15}/> Local edition runs offline</span></div></div>
        <div className={styles.heroArt} aria-label="Illustration of one encrypted document becoming attributable recipient copies"><div className={styles.artGrid}/><span className={styles.artIndex}>PROVENANCE / 001</span><div className={styles.artDoc}><div><FileText size={24}/><span>PDF / ENCRYPTED</span></div><i/><i/><i/><strong><LockKeyhole size={14}/> ONE CIPHERTEXT</strong></div><div className={styles.artConnect}/><div className={styles.artPeople}>{["R1", "R2", "R3"].map(id => <span key={id}>{id}<KeyRound size={17}/></span>)}</div><div className={styles.artTrace}><Fingerprint size={22}/><div><strong>Distinct copy per access</strong><small>Watermark + signature + ledger record</small></div><ArrowRight size={17}/></div><span className={styles.artFoot}>ILLUSTRATIVE FLOW · LIVE EVIDENCE AFTER SIGN-IN</span></div>
      </div></section>

      <section id="journey" className={styles.journey}><div className={styles.wrap}><div className={styles.sectionIntro} data-reveal><span className={styles.kicker}>THE CHAIN OF CUSTODY</span><h2>One continuous story, four distinct responsibilities.</h2><p>The same document moves through distribution, access, investigation and review. Each role sees the tools needed for its part.</p></div><div className={styles.journeyGrid} data-reveal>
        {[
          { icon: FileKey2, title: "Encrypt once", text: "A single encrypted PDF is prepared for selected recipients." },
          { icon: Fingerprint, title: "Mark each copy", text: "Every decryption creates a fresh content-based watermark." },
          { icon: ScanSearch, title: "Analyze a found PDF", text: "The investigator measures the signal in rendered pages." },
          { icon: Database, title: "Verify the evidence", text: "Signatures, hashes and validator quorum are checked." },
        ].map((item, index) => { const Icon = item.icon; return <div key={item.title}><span>0{index + 1}</span><Icon size={24}/><strong>{item.title}</strong><p>{item.text}</p></div>; })}
      </div></div></section>

      <section id="roles" className={styles.rolesIntro}><div className={styles.wrap}><span className={styles.kicker}>ROLE-BASED ACCESS</span><h2>Choose where you enter the story.</h2><p>Explore each workspace, then sign in with its fictional demo account.</p><div className={styles.roleIndex}>{roles.map(role => <a href={`#${role.id}`} key={role.id}><span>{role.number}</span>{role.label}<ArrowDown size={14}/></a>)}</div></div></section>

      {roles.map(role => { const Icon = role.icon; return <section id={role.id} key={role.id} data-scene className={`${styles.roleSection} ${styles[role.id]}`}><div className={`${styles.wrap} ${styles.roleGrid}`}><div className={styles.roleCopy} data-reveal><span className={styles.roleOverline}><b>{role.number} / 04</b> {role.label.toUpperCase()}</span><span className={styles.roleIcon}><Icon size={29}/></span><h2>{role.title}<br/><em>{role.accent}</em></h2><p>{role.description}</p><ul>{role.tasks.map(task => <li key={task}><Check size={16}/>{task}</li>)}</ul><div className={styles.roleActions}><button type="button" onClick={() => choose(role.account)}>{role.action} <ArrowRight size={17}/></button><a href={`#${role.next}`}>Next: {role.nextLabel} <ArrowDown size={16}/></a></div></div><div className={styles.previewWrap} data-reveal><RolePreview role={role.id}/></div></div></section>; })}

      <section id="access" className={styles.access}><div className={`${styles.wrap} ${styles.accessGrid}`}><div className={styles.accessCopy}><span className={styles.lightKicker}>READY TO EXPLORE?</span><h2>Enter the demonstrator.</h2><p>Choose a fictional demo account. Each sign-in opens only the workspace permitted for that role.</p><div className={styles.accountChoices}>{roles.map(role => <button type="button" key={role.id} onClick={() => choose(role.account)}>{role.label}</button>)}</div><small>{HOSTED_DEMO ? "Hosted research demo · Temporary storage · Synthetic documents only" : "Standards-based research prototype · Runs on localhost · No real classified material"}</small></div><div className={styles.signInCard}><div className={styles.signInHeading}><span><LockKeyhole size={20}/></span><div><strong>Role sign-in</strong><small>DEMO ACCOUNT ACCESS</small></div></div><form onSubmit={event => { event.preventDefault(); onSignIn(); }}><label htmlFor="login-user">Account ID</label><input id="login-user" list="demo-accounts" value={loginUser} onChange={event => setLoginUser(event.target.value)} autoComplete="username" required/><datalist id="demo-accounts"><option value="sender"/><option value="REC-001"/><option value="REC-002"/><option value="REC-003"/><option value="investigator"/><option value="auditor"/></datalist><label htmlFor="login-password">Password</label><input ref={passwordRef} id="login-password" type="password" value={loginPassword} onChange={event => setLoginPassword(event.target.value)} autoComplete="current-password" required/>{loginError && <p role="alert" className={styles.loginError}>{loginError}</p>}<button type="submit" disabled={loginBusy || !loginPassword}>{loginBusy ? <><span className={styles.spinner}/> Signing in…</> : <>Sign in <ArrowRight size={17}/></>}</button></form><details className={styles.credentials}><summary>Show fictional demo credentials</summary><dl><dt>sender</dt><dd>Sender-2026!</dd><dt>REC-002</dt><dd>Meera-2026!</dd><dt>investigator</dt><dd>Investigator-2026!</dd><dt>auditor</dt><dd>Auditor-2026!</dd></dl><p>Other seeded recipient accounts are listed in the README.</p></details><p className={styles.loginNote}>These published credentials are for fictional demo accounts only. Sessions and permissions are checked by the API.</p></div></div></section>
    </main>
    <footer className={styles.footer}><div className={styles.wrap}><div><ShieldCheck size={20}/><strong>SourceX</strong><span>SIH26237 · Standards-based research prototype</span></div><a href="#top">Back to top <ArrowUpRight size={15}/></a></div><p>SIH 2026 Prototype — Not an official Ministry of Defence deployment. For fictional identities and synthetic PDFs only. Technical attribution identifies a decrypted copy, not who disclosed it.</p><details className={styles.credits}><summary>Image credits</summary><p>Photographs: Ministry of Defence / Press Information Bureau, Government of India.</p><ul>{Object.entries(photoCredits).map(([key, credit]) => <li key={key}><a href={credit.source} target="_blank" rel="noreferrer">{credit.label} <ArrowUpRight size={12}/></a></li>)}</ul></details></footer>
  </div>;
}
