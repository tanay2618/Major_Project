/**
 * DocumentVerify.jsx
 *
 * Route: /applicant/document
 * Env:   VITE_API_BASE_URL  (frontend/.env, e.g. "http://localhost:8000")
 *
 * Aadhaar verification flow:  Upload -> Quality -> QR decode -> Signature -> Cross-match
 *
 * Every step talks to the real backend (see USE_REAL below):
 *
 *   upload      POST   /api/verify/upload
 *   quality     POST   /api/verify/{id}/quality
 *   qr          POST   /api/verify/{id}/qr
 *   signature   POST   /api/verify/{id}/signature
 *   crossmatch  POST   /api/verify/{id}/crossmatch   (OCR + checksum + final decision)
 *
 * A step set to false in USE_REAL shows clearly labelled DEMO data instead, which is handy
 * for working on the UI without the backend.
 *
 * Every request sends  Authorization: Bearer <kyc_token>  (saved by the Login page).
 * Run the backend from /backend with:  uvicorn main:app --reload
 *
 * Privacy: document data lives in component state/refs only. Nothing is written to
 * localStorage/sessionStorage and nothing is logged to the console.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  HiOutlineCloudArrowUp,
  HiOutlineDocumentCheck,
  HiOutlineShieldCheck,
  HiOutlineTableCells,
  HiOutlineCheckCircle,
  HiOutlineXCircle,
  HiOutlineExclamationTriangle,
  HiOutlineArrowPath,
  HiOutlineTrash,
  HiOutlineInformationCircle,
  HiOutlineLockClosed,
  HiOutlineChevronRight,
  HiOutlineDocumentArrowDown,
  HiOutlineAdjustmentsHorizontal,
} from "react-icons/hi2";
import { IoCheckmarkCircle, IoAlertCircle, IoWarning } from "react-icons/io5";
import "../styles/DocumentVerify.css";

/* ─────────────────────── Configuration ─────────────────────── */

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// true = call the real backend, false = show demo data for that step
const USE_REAL = {
  upload: true,
  quality: true,
  qr: true,
  signature: true,
  crossmatch: true,
};

const DEMO_STEP_LABELS = {
  qr: "QR decode",
  signature: "Signature check",
  crossmatch: "Cross-match",
};
const DEMO_STEPS_IN_USE = Object.keys(DEMO_STEP_LABELS).filter((k) => !USE_REAL[k]);

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "application/pdf"];
const MAX_SIZE_BYTES = 5 * 1024 * 1024; // 5 MB (the backend enforces this too)

const STEP_DEFS = [
  { key: "upload", label: "Upload", icon: HiOutlineCloudArrowUp },
  { key: "quality", label: "Quality", icon: HiOutlineAdjustmentsHorizontal },
  { key: "qr", label: "QR Decode", icon: HiOutlineDocumentCheck },
  { key: "signature", label: "Signature", icon: HiOutlineShieldCheck },
  { key: "crossmatch", label: "Cross-match", icon: HiOutlineTableCells },
];
const STEP_HINTS = [
  "Sending your document securely.",
  "This usually takes a few seconds.",
  "Looking for the QR code. Dense QR codes can take a few seconds.",
  "Checking the signature against UIDAI's public certificate.",
  "Reading the text on the card. This can take up to half a minute.",
];
const INITIAL_STATUSES = ["active", "idle", "idle", "idle", "idle"];

const DEMO_SCENARIOS = [
  { value: "verified", label: "Verified" },
  { value: "tampered", label: "Tampered (name mismatch)" },
  { value: "forged", label: "Forged (bad signature)" },
  { value: "old_qr", label: "Old unsigned QR" },
  { value: "no_qr", label: "No QR found" },
  { value: "network", label: "Network error" },
];

/* ─────────────────────── Small helpers ─────────────────────── */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class ApiError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.status = status;
  }
}

function getToken() {
  try {
    return localStorage.getItem("kyc_token");
  } catch {
    return null; // storage blocked
  }
}

async function apiFetch(path, { method = "POST", body, signal } = {}) {
  const token = getToken();
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      body,
      signal,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("Could not reach the server. Check that the backend is running.", 0);
  }

  if (!res.ok) {
    let detail = "";
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* body was not JSON */
    }
    if (res.status === 401)
      throw new ApiError("Your login has expired. Please log in again.", 401);
    if (res.status === 404)
      throw new ApiError(detail || "This verification session expired. Please start again.", 404);
    if (res.status === 429)
      throw new ApiError(detail || "Too many attempts. Please wait a minute and try again.", 429);
    throw new ApiError(detail || `Request failed (${res.status}).`, res.status);
  }
  if (res.status === 204) return null;
  return res.json();
}

const initialsOf = (name) =>
  (name || "")
    .split(/\s+/)
    .filter(Boolean)
    .map((p) => p[0].toUpperCase() + ".")
    .join(" ");

const yearOf = (dob) => {
  const m = /(\d{4})/.exec(dob || "");
  return m ? m[1] : null;
};

const maskAadhaar = (last4) => (last4 ? `XXXX XXXX ${last4}` : "—");

function riskLevel(score) {
  if (score == null) return { label: "Not assessed", cls: "dv-result__risk--none" };
  if (score < 40) return { label: "Low", cls: "dv-result__risk--low" };
  if (score < 70) return { label: "Medium", cls: "dv-result__risk--medium" };
  return { label: "High", cls: "dv-result__risk--high" };
}

/* ─────────────────────── API layer ─────────────────────── */

async function apiUpload(file, consent, signal) {
  if (!USE_REAL.upload) {
    await sleep(900);
    return { sessionId: "demo-" + Date.now() };
  }
  const fd = new FormData();
  fd.append("file", file);
  fd.append("docType", "aadhaar");
  fd.append("consent", String(consent));
  return apiFetch("/api/verify/upload", { body: fd, signal });
}

async function apiQuality(sessionId, signal) {
  if (!USE_REAL.quality) {
    await sleep(900);
    return { passed: true, score: 90, reason: null, checks: [] };
  }
  return apiFetch(`/api/verify/${sessionId}/quality`, { signal });
}

async function apiQr(sessionId, scenario, signal) {
  if (!USE_REAL.qr) {
    await sleep(1200);
    return getDemoQr(scenario);
  }
  return apiFetch(`/api/verify/${sessionId}/qr`, { signal });
}

async function apiSignature(sessionId, scenario, signal) {
  if (!USE_REAL.signature) {
    await sleep(1000);
    return getDemoSignature(scenario);
  }
  return apiFetch(`/api/verify/${sessionId}/signature`, { signal });
}

async function apiCrossMatch(sessionId, scenario, signal) {
  if (!USE_REAL.crossmatch) {
    await sleep(1200);
    return getDemoCrossMatch(scenario);
  }
  return apiFetch(`/api/verify/${sessionId}/crossmatch`, { signal });
}

function apiDeleteSession(sessionId) {
  if (!USE_REAL.upload || !sessionId) return Promise.resolve();
  const token = getToken();
  return fetch(`${API_BASE}/api/verify/${sessionId}`, {
    method: "DELETE",
    keepalive: true,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  }).catch(() => {});
}

/* ─────────────────────── Demo data (steps not built yet) ─────────────────────── */

function getDemoQr(scenario) {
  if (scenario === "network") throw new ApiError("Could not reach the server.", 0);
  if (scenario === "no_qr") return { qrFound: false, qrType: null, fields: null };
  return {
    qrFound: true,
    qrType: scenario === "old_qr" ? "old" : "secure",
    fields: {
      name: "Rajesh Kumar Sharma",
      dob: "15-08-1990",
      gender: "M",
      last4: "7823",
      pincode: "411001",
    },
  };
}

function getDemoSignature(scenario) {
  if (scenario === "forged")
    return {
      signatureValid: false,
      issuer: null,
      reason: "RSA signature verification failed against the UIDAI public key.",
    };
  if (scenario === "old_qr")
    return {
      signatureValid: null,
      issuer: null,
      reason: "Old unsigned QR: there is no digital signature to verify.",
    };
  return {
    signatureValid: true,
    issuer: "UIDAI (Unique Identification Authority of India)",
    reason: "RSA signature verified against the UIDAI public certificate.",
  };
}

function getDemoCrossMatch(scenario) {
  const fields = [
    { key: "Name", printed: "Rajesh Kumar Sharma", qr: "Rajesh Kumar Sharma", status: "match", similarity: 100 },
    { key: "DOB", printed: "15-08-1990", qr: "15-08-1990", status: "match", similarity: 100 },
    { key: "Gender", printed: "Male", qr: "M", status: "match", similarity: 100 },
    { key: "Aadhaar (last 4)", printed: "XXXX XXXX 7823", qr: "XXXX XXXX 7823", status: "match", similarity: 100 },
    { key: "Pincode", printed: null, qr: "411001", status: "not_checked", similarity: null },
  ];
  switch (scenario) {
    case "tampered":
      fields[0] = { key: "Name", printed: "Rajesh K. Verma", qr: "Rajesh Kumar Sharma", status: "mismatch", similarity: 42 };
      return { fields, riskScore: 78, outcome: "tampered" };
    case "forged":
      return { fields, riskScore: 95, outcome: "forged" };
    case "old_qr":
      return { fields, riskScore: 45, outcome: "manual_review" };
    default:
      return { fields, riskScore: 8, outcome: "verified" };
  }
}

function demoReasons(outcome) {
  switch (outcome) {
    case "verified":
      return ["The digital signature is valid.", "All printed fields match the signed QR data."];
    case "tampered":
      return ["One or more printed fields do not match the signed QR data."];
    case "forged":
      return ["The digital signature could not be verified."];
    default:
      return ["The QR code could not be fully verified, so a person needs to review this."];
  }
}

/* ─────────────────────── Sub-components ─────────────────────── */

function Stepper({ currentStep, stepStatuses }) {
  return (
    <div className="dv-stepper" role="list" aria-label="Verification progress">
      {STEP_DEFS.map((s, i) => {
        const Icon = s.icon;
        const status = stepStatuses[i]; // idle | active | loading | success | warning | error
        let cls = "dv-stepper__step";
        if (i < currentStep) cls += " dv-stepper__step--done";
        if (i === currentStep) cls += " dv-stepper__step--active";
        if (status === "loading") cls += " dv-stepper__step--loading";
        if (status === "error") cls += " dv-stepper__step--error";
        if (status === "warning") cls += " dv-stepper__step--warning";

        return (
          <div key={s.key} className="dv-stepper__item" role="listitem">
            <div className={cls}>
              <div className="dv-stepper__circle">
                {status === "success" ? (
                  <HiOutlineCheckCircle className="dv-stepper__icon dv-stepper__icon--done" />
                ) : status === "error" ? (
                  <HiOutlineXCircle className="dv-stepper__icon dv-stepper__icon--error" />
                ) : status === "warning" ? (
                  <HiOutlineExclamationTriangle className="dv-stepper__icon dv-stepper__icon--error" />
                ) : (
                  <Icon className="dv-stepper__icon" />
                )}
              </div>
              <span className="dv-stepper__label">{s.label}</span>
            </div>
            {i < STEP_DEFS.length - 1 && (
              <div
                className={`dv-stepper__connector ${
                  i < currentStep ? "dv-stepper__connector--done" : ""
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

function StepCard({ title, subtitle, children, status, demo }) {
  let borderClass = "";
  if (status === "success") borderClass = "dv-card--success";
  if (status === "error") borderClass = "dv-card--error";
  if (status === "warning") borderClass = "dv-card--warning";

  return (
    <div className={`dv-card ${borderClass}`}>
      <div className="dv-card__header">
        <h3 className="dv-card__title">
          {title}
          {demo && <span className="dv-demo-tag">Demo data</span>}
        </h3>
        {subtitle && <p className="dv-card__subtitle">{subtitle}</p>}
      </div>
      <div className="dv-card__body">{children}</div>
    </div>
  );
}

function UploadZone({ file, preview, onFileSelect, onRemove, disabled }) {
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragOver(false);
      if (disabled) return;
      const f = e.dataTransfer.files?.[0];
      if (f) onFileSelect(f);
    },
    [disabled, onFileSelect]
  );

  const handleChange = (e) => {
    const f = e.target.files?.[0];
    if (f) onFileSelect(f);
    e.target.value = "";
  };

  if (file && preview) {
    return (
      <div className="dv-upload__preview-wrap">
        {file.type === "application/pdf" ? (
          <div className="dv-upload__pdf-badge">
            <HiOutlineDocumentCheck className="dv-upload__pdf-icon" />
            <span>{file.name}</span>
          </div>
        ) : (
          <img src={preview} alt="Document preview" className="dv-upload__preview-img" />
        )}
        <button className="dv-upload__remove-btn" onClick={onRemove} disabled={disabled}>
          <HiOutlineTrash />
          <span>Remove</span>
        </button>
      </div>
    );
  }

  return (
    <div
      className={`dv-upload__zone ${dragOver ? "dv-upload__zone--drag" : ""} ${
        disabled ? "dv-upload__zone--disabled" : ""
      }`}
      onDrop={handleDrop}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => {
        if ((e.key === "Enter" || e.key === " ") && !disabled) {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-label="Upload your Aadhaar image or PDF"
    >
      <input
        ref={inputRef}
        type="file"
        accept=".jpg,.jpeg,.png,.pdf"
        onChange={handleChange}
        className="dv-upload__input"
        disabled={disabled}
        data-testid="file-input"
      />
      <HiOutlineCloudArrowUp className="dv-upload__drop-icon" />
      <p className="dv-upload__drop-text">
        Drag &amp; drop your Aadhaar here, or <span className="dv-upload__browse">browse</span>
      </p>
      <p className="dv-upload__drop-hint">JPG, PNG or PDF, max 5 MB</p>
    </div>
  );
}

function Spinner({ text }) {
  return (
    <div className="dv-spinner-wrap">
      <div className="dv-spinner" />
      {text && <p className="dv-spinner__text">{text}</p>}
    </div>
  );
}

function QualityCard({ quality }) {
  const warnings = quality.checks.filter((c) => !c.passed && !c.critical).length;
  const status = !quality.passed ? "error" : warnings ? "warning" : "success";

  const icon = (c) =>
    c.passed ? (
      <IoCheckmarkCircle className="dv-table__icon dv-table__icon--match" />
    ) : c.critical ? (
      <IoAlertCircle className="dv-table__icon dv-table__icon--mismatch" />
    ) : (
      <IoWarning className="dv-table__icon dv-table__icon--partial" />
    );

  return (
    <StepCard title="Image quality check" status={status}>
      <div className="dv-qr-badges">
        <span className={`dv-badge ${quality.passed ? "dv-badge--green" : "dv-badge--red"}`}>
          {quality.passed ? "Quality OK" : "Quality too low"}
        </span>
        <span className="dv-badge dv-badge--amber">Score {quality.score}/100</span>
      </div>

      <ul className="dv-checks">
        {quality.checks.map((c) => (
          <li key={c.key} className="dv-checks__item">
            {icon(c)}
            <div>
              <span className="dv-checks__label">{c.label}</span>
              <span className="dv-checks__msg">{c.message}</span>
            </div>
          </li>
        ))}
      </ul>
    </StepCard>
  );
}

function CrossMatchTable({ fields }) {
  if (!fields || fields.length === 0) return null;

  const statusIcon = (s) => {
    if (s === "match") return <IoCheckmarkCircle className="dv-table__icon dv-table__icon--match" />;
    if (s === "mismatch") return <IoAlertCircle className="dv-table__icon dv-table__icon--mismatch" />;
    if (s === "not_checked") return <HiOutlineInformationCircle className="dv-table__icon dv-table__icon--none" />;
    return <IoWarning className="dv-table__icon dv-table__icon--partial" />;
  };
  const statusLabel = (f) => {
    const s = f.status;
    if (s === "match") return "✓ Match";
    if (s === "mismatch") return "✗ Mismatch";
    if (s !== "not_checked") return "~ Partial";
    // Say WHY nothing was compared, so a value the OCR did read is never called "not visible".
    if (f.key === "Aadhaar checksum") {
      return f.printed && /x/i.test(f.printed) ? "Can't check: number is masked" : "Not checked";
    }
    if (f.printed && !f.qr) return "Not stored in QR";
    if (!f.printed && f.qr) return "Not read from card";
    return "Not visible on card";
  };

  return (
    <div className="dv-table-wrap">
      <table className="dv-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Printed on card (OCR)</th>
            <th>Signed QR data</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f.key}>
              <td className="dv-table__field">{f.key}</td>
              <td>{f.printed ?? "—"}</td>
              <td>{f.qr ?? "—"}</td>
              <td className={`dv-table__status dv-table__status--${f.status}`}>
                {statusIcon(f.status)}
                <span>{statusLabel(f)}</span>
                {f.key === "Name" && f.similarity != null && (
                  <span className="dv-table__sim">({f.similarity}%)</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const RESULT_CONFIG = {
  verified: {
    cls: "dv-result--verified",
    icon: <IoCheckmarkCircle className="dv-result__icon" />,
    title: "Verified",
    desc: "The digital signature is valid and all printed fields match the signed QR data.",
  },
  likely_authentic: {
    cls: "dv-result--likely",
    icon: <IoCheckmarkCircle className="dv-result__icon" />,
    title: "Likely authentic",
    desc: "The printed name, Aadhaar number and pincode match the QR code. The QR is not digitally signed, so this is a strong sign, not proof.",
  },
  tampered: {
    cls: "dv-result--tampered",
    icon: <IoAlertCircle className="dv-result__icon" />,
    title: "Possible tampering, flagged",
    desc: "The card shows signs of having been altered.",
  },
  forged: {
    cls: "dv-result--forged",
    icon: <HiOutlineXCircle className="dv-result__icon" />,
    title: "Forged or invalid document",
    desc: "The digital signature could not be verified. This document may be fabricated.",
  },
  low_quality: {
    cls: "dv-result--lowq",
    icon: <HiOutlineAdjustmentsHorizontal className="dv-result__icon" />,
    title: "Image quality too low",
    desc: "We could not check this document reliably. Please upload a clearer photo or scan.",
  },
  manual_review: {
    cls: "dv-result--manual",
    icon: <IoWarning className="dv-result__icon" />,
    title: "Needs manual review",
    desc: "This document could not be fully verified automatically.",
  },
};

function ResultCard({ final, demo, onReset, onRetake, onDownload }) {
  const c = RESULT_CONFIG[final.outcome] || RESULT_CONFIG.manual_review;
  const risk = riskLevel(final.riskScore);

  return (
    <div className={`dv-result ${c.cls}`} role="region" aria-label="Verification result">
      <div className="dv-result__header">
        {c.icon}
        <div>
          <h3 className="dv-result__title">{c.title}</h3>
          <p className="dv-result__desc">{c.desc}</p>
        </div>
      </div>

      {final.reasons?.length > 0 && (
        <ul className="dv-reasons">
          {final.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}

      <div className="dv-result__meta">
        <div className="dv-result__meta-item">
          <span className="dv-result__meta-label">Risk score</span>
          <span className="dv-result__meta-value">
            {final.riskScore != null ? `${final.riskScore}/100` : "—"}
          </span>
        </div>
        <div className="dv-result__meta-item">
          <span className="dv-result__meta-label">Risk level</span>
          <span className={`dv-result__risk ${risk.cls}`}>{risk.label}</span>
        </div>
      </div>

      {demo && (
        <p className="dv-demo-note">
          <HiOutlineInformationCircle />
          Part of this result uses demo data ({DEMO_STEPS_IN_USE.map((k) => DEMO_STEP_LABELS[k]).join(", ")}{" "}
          not connected to the backend yet). Do not treat it as a real verdict.
        </p>
      )}

      <div className="dv-result__actions">
        {final.outcome === "low_quality" ? (
          <button className="dv-btn dv-btn--primary" onClick={onRetake}>
            <HiOutlineArrowPath />
            <span>Re-upload a clearer image</span>
          </button>
        ) : (
          <button className="dv-btn dv-btn--primary" onClick={onReset}>
            <HiOutlineArrowPath />
            <span>Verify another document</span>
          </button>
        )}
        <button className="dv-btn dv-btn--outline" onClick={onDownload}>
          <HiOutlineDocumentArrowDown />
          <span>Download report (JSON)</span>
        </button>
      </div>

      <p className="dv-result__footer-note">
        <HiOutlineLockClosed />
        Your uploaded document has been removed from our server.
      </p>
    </div>
  );
}

/* ─────────────────────── Main component ─────────────────────── */

export default function DocumentVerify() {
  const navigate = useNavigate();

  /* ── State ── */
  const [currentStep, setCurrentStep] = useState(0);
  const [stepStatuses, setStepStatuses] = useState(INITIAL_STATUSES);
  const [started, setStarted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("");

  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [consent, setConsent] = useState(false);
  const [fileError, setFileError] = useState("");
  const [uploadError, setUploadError] = useState("");

  const [results, setResults] = useState({}); // { quality, qr, signature, crossmatch }
  const [final, setFinal] = useState(null); // { outcome, riskScore, reasons }
  const [error, setError] = useState(null); // { step, message, status }
  const [scenario, setScenario] = useState("verified"); // only used by demo steps

  // Refs: values the async pipeline must read without waiting for a re-render.
  const sessionRef = useRef(null);
  const abortRef = useRef(null);
  const previewUrlRef = useRef(null);

  /* ── Cleanup on unmount: abort requests, free the preview, delete the session ── */
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
      apiDeleteSession(sessionRef.current);
      sessionRef.current = null;
    };
  }, []);

  /* ── File handling ── */

  const handleFileSelect = useCallback((f) => {
    setFileError("");
    if (!ACCEPTED_TYPES.includes(f.type)) {
      setFileError("Unsupported file type. Please upload a JPG, PNG or PDF.");
      return;
    }
    if (f.size > MAX_SIZE_BYTES) {
      setFileError(`File too large (${(f.size / 1024 / 1024).toFixed(1)} MB). Maximum is 5 MB.`);
      return;
    }
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    const url = f.type !== "application/pdf" ? URL.createObjectURL(f) : null;
    previewUrlRef.current = url;
    setFile(f);
    setPreview(url || "pdf");
  }, []);

  const handleRemoveFile = useCallback(() => {
    if (previewUrlRef.current) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
    setFile(null);
    setPreview(null);
    setFileError("");
  }, []);

  /* ── Helpers ── */

  const setStepStatus = (idx, status) =>
    setStepStatuses((prev) => prev.map((s, i) => (i === idx ? status : s)));

  const setResult = (key, value) => setResults((prev) => ({ ...prev, [key]: value }));

  const discardSession = () => {
    apiDeleteSession(sessionRef.current);
    sessionRef.current = null;
  };

  const resetRun = () => {
    setCurrentStep(0);
    setStepStatuses(INITIAL_STATUSES);
    setStarted(false);
    setLoading(false);
    setLoadingText("");
    setResults({});
    setFinal(null);
    setError(null);
    setUploadError("");
  };

  /* ── Pipeline: runs steps in order, can resume from any step ── */

  const runFrom = async (startIdx) => {
    if (!file || !consent) return;

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const { signal } = ac;

    // Clear what this run will recompute.
    setError(null);
    setUploadError("");
    setFinal(null);
    setStarted(true);
    setLoading(true);
    setStepStatuses((prev) => prev.map((s, i) => (i >= startIdx ? "idle" : s)));
    setResults((prev) => {
      const keep = {};
      if (startIdx > 1 && prev.quality) keep.quality = prev.quality;
      if (startIdx > 2 && prev.qr) keep.qr = prev.qr;
      if (startIdx > 3 && prev.signature) keep.signature = prev.signature;
      return keep;
    });

    const finish = (outcome, riskScore, reasons) => setFinal({ outcome, riskScore, reasons });

    const steps = [
      {
        text: "Uploading document…",
        run: async () => {
          const { sessionId } = await apiUpload(file, consent, signal);
          sessionRef.current = sessionId;
        },
      },
      {
        text: "Checking image quality…",
        run: async () => {
          const q = await apiQuality(sessionRef.current, signal);
          setResult("quality", q);
          if (!q.passed) {
            finish("low_quality", null, [q.reason]);
            discardSession(); // nothing more to do with a bad image
            return "stop-error";
          }
        },
      },
      {
        text: "Scanning for the QR code…",
        run: async () => {
          const qr = await apiQr(sessionRef.current, scenario, signal);
          setResult("qr", qr);
          if (!qr.qrFound) {
            finish("manual_review", null, [
              "No QR code was found on the document.",
              "Upload the side of your Aadhaar that has the QR code.",
            ]);
            return "stop-error";
          }
        },
      },
      {
        text: "Verifying the digital signature…",
        run: async () => {
          const sig = await apiSignature(sessionRef.current, scenario, signal);
          setResult("signature", sig);
          // valid -> tick; not checkable (old unsigned QR, no certificate) -> amber warning; invalid -> red cross
          return sig.signatureValid === true ? "success" : sig.signatureValid === false ? "error" : "warning";
        },
      },
      {
        text: "Cross-matching printed text with QR data…",
        run: async () => {
          const cm = await apiCrossMatch(sessionRef.current, scenario, signal);
          setResult("crossmatch", cm);
          finish(cm.outcome, cm.riskScore, cm.reasons || demoReasons(cm.outcome));
          discardSession();
          if (cm.outcome === "verified" || cm.outcome === "likely_authentic") return "success";
          return cm.outcome === "manual_review" ? "warning" : "error";
        },
      },
    ];

    for (let i = startIdx; i < steps.length; i++) {
      setCurrentStep(i);
      setStepStatus(i, "loading");
      setLoadingText(steps[i].text);
      try {
        const outcome = await steps[i].run();
        if (signal.aborted) return;
        if (outcome === "stop-error") {
          setStepStatus(i, "error");
          setLoading(false);
          return;
        }
        setStepStatus(i, outcome === "error" || outcome === "warning" ? outcome : "success");
      } catch (e) {
        if (e.name === "AbortError") return;
        const message = e instanceof ApiError ? e.message : "Something went wrong. Please try again.";
        setStepStatus(i, "error");
        setLoading(false);
        if (i === 0) {
          // Upload problems are shown on the upload form itself.
          setStarted(false);
          setStepStatuses(INITIAL_STATUSES);
          setCurrentStep(0);
          setUploadError(message);
          if (e.status === 400) handleRemoveFile(); // the file itself was rejected
        } else {
          setError({ step: i, message, status: e.status || 0 });
        }
        return;
      }
    }
    setCurrentStep(steps.length);
    setLoading(false);
  };

  /* ── Button handlers ── */

  const handleCancel = () => {
    abortRef.current?.abort();
    discardSession();
    resetRun();
  };

  const handleReset = () => {
    abortRef.current?.abort();
    discardSession();
    handleRemoveFile();
    setConsent(false);
    resetRun();
  };

  // Back to the upload form with a fresh file, keeping the consent tick.
  const handleRetake = () => {
    abortRef.current?.abort();
    discardSession();
    handleRemoveFile();
    resetRun();
  };

  const handleRetry = () => {
    if (!error) return;
    // A 404 means the server forgot the session, so start again from the upload.
    runFrom(error.status === 404 ? 0 : error.step);
  };

  const handleDownloadReport = () => {
    // Privacy: the report carries no document images and no full personal details.
    const qrFields = results.qr?.fields;
    const report = {
      generatedAt: new Date().toISOString(),
      outcome: final?.outcome ?? null,
      riskScore: final?.riskScore ?? null,
      reasons: final?.reasons ?? [],
      usesDemoData: DEMO_STEPS_IN_USE.length > 0,
      quality: results.quality
        ? {
            passed: results.quality.passed,
            score: results.quality.score,
            checks: results.quality.checks.map((c) => ({ key: c.key, passed: c.passed, value: c.value })),
          }
        : null,
      qr: results.qr
        ? {
            qrFound: results.qr.qrFound,
            qrType: results.qr.qrType,
            fields: qrFields
              ? {
                  nameInitials: initialsOf(qrFields.name),
                  birthYear: yearOf(qrFields.dob),
                  aadhaar: maskAadhaar(qrFields.last4),
                }
              : null,
          }
        : null,
      signature: results.signature
        ? { signatureValid: results.signature.signatureValid, issuer: results.signature.issuer }
        : null,
      crossMatch: results.crossmatch
        ? {
            ocrConfidence: results.crossmatch.ocr?.confidence ?? null,
            checksumValid: results.crossmatch.ocr?.verhoeffValid ?? null,
            fields: results.crossmatch.fields.map((f) => ({ field: f.key, status: f.status, similarity: f.similarity })),
          }
        : null,
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `kyc-report-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /* ── Render ── */

  const canStart = file && consent && !loading;
  const { quality, qr, signature, crossmatch } = results;
  const usedDemo = DEMO_STEPS_IN_USE.length > 0 && Boolean(qr || signature || crossmatch);
  const announcement = final
    ? `Result: ${RESULT_CONFIG[final.outcome]?.title ?? "finished"}`
    : loading
    ? loadingText
    : error
    ? error.message
    : "";

  return (
    <div className="dv">
      <div className="dv__container">
        <div className="dv__header">
          <h1 className="dv__title">Verify your Aadhaar</h1>
          <p className="dv__subtitle">
            Upload your Aadhaar card. We check the image quality, read the Secure QR code, verify its
            digital signature and compare it with the printed text.
          </p>
        </div>

        {DEMO_STEPS_IN_USE.length > 0 && (
          <div className="dv-demo-banner">
            <HiOutlineInformationCircle />
            <span>
              Work in progress: <strong>upload and quality check are real</strong>.{" "}
              {DEMO_STEPS_IN_USE.map((k) => DEMO_STEP_LABELS[k]).join(", ")} still show demo data.
            </span>
          </div>
        )}

        {import.meta.env.DEV && DEMO_STEPS_IN_USE.length > 0 && (
          <label className="dv-dev">
            Demo scenario (dev only)
            <select value={scenario} onChange={(e) => setScenario(e.target.value)} disabled={loading}>
              {DEMO_SCENARIOS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="dv-sr-only" role="status" aria-live="polite">
          {announcement}
        </div>

        <Stepper currentStep={currentStep} stepStatuses={stepStatuses} />

        {/* Upload form */}
        {!started && (
          <StepCard
            title="Upload your document"
            subtitle="Upload the side of your Aadhaar that has the QR code."
          >
            <UploadZone
              file={file}
              preview={preview}
              onFileSelect={handleFileSelect}
              onRemove={handleRemoveFile}
              disabled={loading}
            />
            {fileError && (
              <p className="dv-error-msg" role="alert">
                <HiOutlineExclamationTriangle /> {fileError}
              </p>
            )}

            <div className="dv-tips">
              <HiOutlineInformationCircle className="dv-tips__icon" />
              <div>
                <strong>Tips for best results</strong>
                <ul className="dv-tips__list">
                  <li>Make sure the QR code is sharp, well lit and fully visible.</li>
                  <li>Avoid glare, shadows and blurry images.</li>
                  <li>Crop the image to show only the card if possible.</li>
                </ul>
              </div>
            </div>

            <label className="dv-consent">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="dv-consent__checkbox"
              />
              <span className="dv-consent__text">
                I consent to my document being processed for verification. Uploaded files are deleted
                right after verification, in line with the{" "}
                <strong>Digital Personal Data Protection Act, 2023</strong>.
              </span>
            </label>

            {uploadError && (
              <div className="dv-error-box" role="alert">
                <HiOutlineXCircle className="dv-error-box__icon" />
                <div>
                  <p>{uploadError}</p>
                  {/log in/i.test(uploadError) && (
                    <button className="dv-btn dv-btn--outline dv-btn--sm" onClick={() => navigate("/login")}>
                      Go to login
                    </button>
                  )}
                </div>
              </div>
            )}

            <div className="dv-step-actions">
              <button
                className="dv-btn dv-btn--primary dv-btn--lg"
                disabled={!canStart}
                onClick={() => runFrom(0)}
              >
                <HiOutlineShieldCheck />
                <span>Start verification</span>
                <HiOutlineChevronRight />
              </button>
            </div>
          </StepCard>
        )}

        {/* Results appear as each step finishes */}
        {started && quality && <QualityCard quality={quality} />}

        {started && qr && (
          <StepCard
            title="QR code detection and decode"
            demo={!USE_REAL.qr}
            status={!qr.qrFound ? "error" : qr.qrType === "old" ? "warning" : "success"}
          >
            <div className="dv-qr-badges">
              <span className={`dv-badge ${qr.qrFound ? "dv-badge--green" : "dv-badge--red"}`}>
                {qr.qrFound ? "QR found" : "QR not found"}
              </span>
              {qr.qrFound && (
                <span
                  className={`dv-badge ${qr.qrType === "secure" ? "dv-badge--green" : "dv-badge--amber"}`}
                >
                  {qr.qrType === "secure" ? "Secure QR (signed)" : "Old QR (unsigned)"}
                </span>
              )}
            </div>

            {qr.fields && (
              <div className="dv-decoded">
                <h4 className="dv-decoded__title">Decoded fields</h4>
                <div className="dv-decoded__grid">
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Name</span>
                    <span className="dv-decoded__value">{qr.fields.name || "—"}</span>
                  </div>
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Date of birth</span>
                    <span className="dv-decoded__value">{qr.fields.dob || "—"}</span>
                  </div>
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Gender</span>
                    <span className="dv-decoded__value">
                      {qr.fields.gender === "M" ? "Male" : qr.fields.gender === "F" ? "Female" : qr.fields.gender === "T" ? "Transgender" : "—"}
                    </span>
                  </div>
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Aadhaar number</span>
                    <span className="dv-decoded__value dv-decoded__value--mono">
                      {maskAadhaar(qr.fields.last4)}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {qr.qrFound && qr.note && qr.qrType !== "old" && (
              <div className="dv-warning-box">
                <HiOutlineExclamationTriangle className="dv-warning-box__icon" />
                <p>{qr.note}</p>
              </div>
            )}

            {qr.qrType === "old" && (
              <div className="dv-warning-box">
                <HiOutlineExclamationTriangle className="dv-warning-box__icon" />
                <p>
                  This QR code uses the old unsigned format and cannot be cryptographically verified. The
                  document will go to <strong>manual review</strong>.
                </p>
              </div>
            )}

            {!qr.qrFound && (
              <div className="dv-error-box">
                <HiOutlineXCircle className="dv-error-box__icon" />
                <div>
                  <p>
                    {qr.note ||
                      "We could not find a QR code in your upload. It may be too small, covered by glare, or cropped out."}
                  </p>
                  <button className="dv-btn dv-btn--outline dv-btn--sm" onClick={handleRetake}>
                    <HiOutlineArrowPath />
                    <span>Re-upload a clearer image</span>
                  </button>
                </div>
              </div>
            )}
          </StepCard>
        )}

        {started && signature && (
          <StepCard
            title="Digital signature verification"
            demo={!USE_REAL.signature}
            status={
              signature.signatureValid === true ? "success" : signature.signatureValid === false ? "error" : "warning"
            }
          >
            <div className="dv-sig">
              {signature.signatureValid === true && (
                <div className="dv-sig__result dv-sig__result--valid">
                  <IoCheckmarkCircle className="dv-sig__icon" />
                  <div>
                    <p className="dv-sig__label">Digital signature valid</p>
                    <p className="dv-sig__issuer">Issued by: {signature.issuer}</p>
                    <p className="dv-sig__reason">{signature.reason}</p>
                  </div>
                </div>
              )}
              {signature.signatureValid === false && (
                <div className="dv-sig__result dv-sig__result--invalid">
                  <IoAlertCircle className="dv-sig__icon" />
                  <div>
                    <p className="dv-sig__label">Signature invalid</p>
                    <p className="dv-sig__reason">{signature.reason}</p>
                  </div>
                </div>
              )}
              {signature.signatureValid === null && (
                <div className="dv-sig__result dv-sig__result--na">
                  <IoWarning className="dv-sig__icon" />
                  <div>
                    <p className="dv-sig__label">Signature check not available</p>
                    <p className="dv-sig__reason">{signature.reason}</p>
                  </div>
                </div>
              )}
            </div>
            <p className="dv-sig__note">
              <HiOutlineInformationCircle />
              <span>
                A valid signature proves the card data is genuine and was issued by UIDAI. It does{" "}
                <em>not</em> prove that the person uploading it is the cardholder. Matching the document
                to its owner is not part of this check.
              </span>
            </p>
          </StepCard>
        )}

        {started && crossmatch && (
          <StepCard
            title="Cross-match: printed card vs QR data"
            demo={!USE_REAL.crossmatch}
            status={
              crossmatch.outcome === "verified" || crossmatch.outcome === "likely_authentic" ? "success" : crossmatch.outcome === "manual_review" ? "warning" : "error"
            }
          >
            <CrossMatchTable fields={crossmatch.fields} />
            {crossmatch.ocr && (
              <p className="dv-table__caption">
                <HiOutlineInformationCircle />
                <span>
                  Text read from the card with {Math.round((crossmatch.ocr.confidence || 0) * 100)}% average
                  confidence.
                  {crossmatch.ocr.verhoeffValid === true && " The Aadhaar number passes its built-in checksum."}
                  {crossmatch.ocr.verhoeffValid === false && " The printed Aadhaar number FAILS its built-in checksum."}
                  {" "}Details that are not stored in the QR, not printed, or masked could not be compared.
                </span>
              </p>
            )}
          </StepCard>
        )}

        {/* Loading */}
        {loading && (
          <StepCard title={loadingText}>
            <Spinner text={STEP_HINTS[currentStep] || "Please wait."} />
            <div className="dv-step-actions">
              <button className="dv-btn dv-btn--outline" onClick={handleCancel}>
                Cancel
              </button>
            </div>
          </StepCard>
        )}

        {/* Error with retry (resumes from the step that failed) */}
        {!loading && error && (
          <div className="dv-error-box dv-error-box--wide" role="alert">
            <HiOutlineXCircle className="dv-error-box__icon" />
            <div>
              <p>{error.message}</p>
              <div className="dv-retry-wrap">
                {error.status === 401 ? (
                  <button className="dv-btn dv-btn--primary" onClick={() => navigate("/login")}>
                    Go to login
                  </button>
                ) : (
                  <button className="dv-btn dv-btn--primary" onClick={handleRetry}>
                    <HiOutlineArrowPath />
                    <span>Try again</span>
                  </button>
                )}
                <button className="dv-btn dv-btn--outline" onClick={handleReset}>
                  Start over
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Final result */}
        {!loading && final && (
          <ResultCard
            final={final}
            demo={usedDemo}
            onReset={handleReset}
            onRetake={handleRetake}
            onDownload={handleDownloadReport}
          />
        )}

        <div className="dv__privacy-footer">
          <HiOutlineLockClosed />
          <span>Your document is processed securely and deleted immediately after verification.</span>
        </div>
      </div>
    </div>
  );
}
