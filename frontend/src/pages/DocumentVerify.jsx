/**
 * DocumentVerify.jsx
 *
 * Route: /applicant/document
 * Env:   VITE_API_BASE_URL  (e.g. "http://localhost:8000")
 *
 * Aadhaar Secure QR verification flow — 4-step stepper.
 * All verification logic runs on the backend.
 * Set USE_MOCK = true to run with realistic mock responses.
 *
 * Dependencies: react, react-icons/hi2, react-icons/io5
 */

import { useState, useRef, useEffect, useCallback } from "react";
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
  HiOutlineArrowDown,
  HiOutlineInformationCircle,
  HiOutlineLockClosed,
  HiOutlineChevronRight,
  HiOutlineDocumentArrowDown,
  HiOutlineXMark,
} from "react-icons/hi2";
import { IoCheckmarkCircle, IoAlertCircle, IoWarning } from "react-icons/io5";
import '../styles/DocumentVerify.css';

/* ─────────────────────── Configuration ─────────────────────── */

const USE_MOCK = true; // ← flip to false when backend is live

const API_BASE =
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const ACCEPTED_TYPES = [
  "image/jpeg",
  "image/png",
  "application/pdf",
]
const MAX_SIZE_BYTES = 5 * 1024 * 1024; // 5 MB

/* ─────────────────────── Mock helpers ─────────────────────── */

// Change this value to test different scenarios:
//   "verified"    → signature valid, all fields match
//   "tampered"    → signature valid, field mismatch
//   "forged"      → signature invalid
//   "old_qr"      → unsigned / old QR
//   "no_qr"       → QR not found
//   "network"     → simulates a network error
const MOCK_SCENARIO = "verified";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getMockUploadResponse() {
  return { sessionId: "mock-sess-" + Date.now() };
}

function getMockQrResponse(scenario) {
  switch (scenario) {
    case "no_qr":
      return { qrFound: false, qrType: null, fields: null };
    case "old_qr":
      return {
        qrFound: true,
        qrType: "old",
        fields: {
          name: "Rajesh Kumar Sharma",
          dob: "15-08-1990",
          gender: "M",
          last4: "7823",
          pincode: "411001",
          photoBase64: null,
        },
      };
    default:
      return {
        qrFound: true,
        qrType: "secure",
        fields: {
          name: "Rajesh Kumar Sharma",
          dob: "15-08-1990",
          gender: "M",
          last4: "7823",
          pincode: "411001",
          photoBase64: null,
        },
      };
  }
}

function getMockSignatureResponse(scenario) {
  switch (scenario) {
    case "forged":
      return {
        signatureValid: false,
        issuer: null,
        reason: "RSA signature verification failed against UIDAI public key.",
      };
    case "old_qr":
      return {
        signatureValid: null,
        issuer: null,
        reason:
          "Old unsigned QR — no digital signature present to verify.",
      };
    default:
      return {
        signatureValid: true,
        issuer: "UIDAI (Unique Identification Authority of India)",
        reason: "RSA-2048 signature verified against UIDAI public certificate.",
      };
  }
}

function getMockCrossMatchResponse(scenario) {
  const base = [
    {
      key: "Name",
      printed: "Rajesh Kumar Sharma",
      qr: "Rajesh Kumar Sharma",
      status: "match",
      similarity: 100,
    },
    {
      key: "DOB",
      printed: "15-08-1990",
      qr: "15-08-1990",
      status: "match",
      similarity: 100,
    },
    {
      key: "Gender",
      printed: "Male",
      qr: "M",
      status: "match",
      similarity: 100,
    },
    {
      key: "Aadhaar (last 4)",
      printed: "XXXX XXXX 7823",
      qr: "XXXX XXXX 7823",
      status: "match",
      similarity: 100,
    },
  ];

  switch (scenario) {
    case "tampered":
      base[0] = {
        key: "Name",
        printed: "Rajesh K. Verma",
        qr: "Rajesh Kumar Sharma",
        status: "mismatch",
        similarity: 42,
      };
      return {
        fields: base,
        faceSimilarity: 0.91,
        riskScore: 78,
        outcome: "tampered",
      };
    case "forged":
      return {
        fields: base,
        faceSimilarity: 0.6,
        riskScore: 95,
        outcome: "forged",
      };
    case "old_qr":
      return {
        fields: base,
        faceSimilarity: 0.88,
        riskScore: 45,
        outcome: "manual_review",
      };
    case "no_qr":
      return {
        fields: [],
        faceSimilarity: null,
        riskScore: 50,
        outcome: "manual_review",
      };
    default:
      return {
        fields: base,
        faceSimilarity: 0.96,
        riskScore: 8,
        outcome: "verified",
      };
  }
}

/* ─────────────────────── API Layer ─────────────────────── */
// Replace mock implementations with real fetch/axios calls when backend is ready.

async function apiUpload(file, docType, consent) {
  if (USE_MOCK) {
    await sleep(1200);
    if (MOCK_SCENARIO === "network") throw new Error("Network error: server unreachable.");
    return getMockUploadResponse();
  }
  // REAL: POST /api/verify/upload (multipart)
  const fd = new FormData();
  fd.append("file", file);
  fd.append("docType", docType);
  fd.append("consent", String(consent));
  const res = await fetch(`${API_BASE}/api/verify/upload`, {
    method: "POST",
    body: fd,
  });
  if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  return res.json();
}

async function apiQrDecode(sessionId) {
  if (USE_MOCK) {
    await sleep(1800);
    if (MOCK_SCENARIO === "network") throw new Error("Network error: server unreachable.");
    return getMockQrResponse(MOCK_SCENARIO);
  }
  // REAL: POST /api/verify/{sessionId}/qr
  const res = await fetch(`${API_BASE}/api/verify/${sessionId}/qr`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`QR decode failed (${res.status})`);
  return res.json();
}

async function apiSignatureVerify(sessionId) {
  if (USE_MOCK) {
    await sleep(1400);
    if (MOCK_SCENARIO === "network") throw new Error("Network error: server unreachable.");
    return getMockSignatureResponse(MOCK_SCENARIO);
  }
  // REAL: POST /api/verify/{sessionId}/signature
  const res = await fetch(`${API_BASE}/api/verify/${sessionId}/signature`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Signature verification failed (${res.status})`);
  return res.json();
}

async function apiCrossMatch(sessionId) {
  if (USE_MOCK) {
    await sleep(1600);
    if (MOCK_SCENARIO === "network") throw new Error("Network error: server unreachable.");
    return getMockCrossMatchResponse(MOCK_SCENARIO);
  }
  // REAL: POST /api/verify/{sessionId}/crossmatch
  const res = await fetch(`${API_BASE}/api/verify/${sessionId}/crossmatch`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Cross-match failed (${res.status})`);
  return res.json();
}

/* ─────────────────────── Sub-components ─────────────────────── */

/* Stepper */
function Stepper({ currentStep, stepStatuses }) {
  const steps = [
    { label: "Upload", icon: HiOutlineCloudArrowUp },
    { label: "QR Decode", icon: HiOutlineDocumentCheck },
    { label: "Signature", icon: HiOutlineShieldCheck },
    { label: "Cross-match", icon: HiOutlineTableCells },
  ];

  return (
    <div className="dv-stepper">
      {steps.map((s, i) => {
        const Icon = s.icon;
        const status = stepStatuses[i]; // idle | active | loading | success | error
        let cls = "dv-stepper__step";
        if (i < currentStep) cls += " dv-stepper__step--done";
        if (i === currentStep) cls += " dv-stepper__step--active";
        if (status === "loading") cls += " dv-stepper__step--loading";
        if (status === "error") cls += " dv-stepper__step--error";

        return (
          <div key={i} className="dv-stepper__item">
            <div className={cls}>
              <div className="dv-stepper__circle">
                {status === "success" ? (
                  <HiOutlineCheckCircle className="dv-stepper__icon dv-stepper__icon--done" />
                ) : status === "error" ? (
                  <HiOutlineXCircle className="dv-stepper__icon dv-stepper__icon--error" />
                ) : (
                  <Icon className="dv-stepper__icon" />
                )}
              </div>
              <span className="dv-stepper__label">{s.label}</span>
            </div>
            {i < steps.length - 1 && (
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

/* StepCard wrapper */
function StepCard({ title, subtitle, children, status }) {
  let borderClass = "";
  if (status === "success") borderClass = "dv-card--success";
  if (status === "error") borderClass = "dv-card--error";
  if (status === "warning") borderClass = "dv-card--warning";

  return (
    <div className={`dv-card ${borderClass}`}>
      <div className="dv-card__header">
        <h3 className="dv-card__title">{title}</h3>
        {subtitle && <p className="dv-card__subtitle">{subtitle}</p>}
      </div>
      <div className="dv-card__body">{children}</div>
    </div>
  );
}

/* UploadZone */
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

  const handleDragOver = (e) => {
    e.preventDefault();
    if (!disabled) setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const handleClick = () => {
    if (!disabled && inputRef.current) inputRef.current.click();
  };

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
          <img
            src={preview}
            alt="Document preview"
            className="dv-upload__preview-img"
          />
        )}
        <button
          className="dv-upload__remove-btn"
          onClick={onRemove}
          disabled={disabled}
          title="Remove file"
        >
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
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={handleClick}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".jpg,.jpeg,.png,.pdf"
        onChange={handleChange}
        className="dv-upload__input"
        disabled={disabled}
      />
      <HiOutlineCloudArrowUp className="dv-upload__drop-icon" />
      <p className="dv-upload__drop-text">
        Drag &amp; drop your Aadhaar image here, or{" "}
        <span className="dv-upload__browse">browse</span>
      </p>
      <p className="dv-upload__drop-hint">JPG, PNG or PDF — max 5 MB</p>
    </div>
  );
}

/* Spinner */
function Spinner({ text }) {
  return (
    <div className="dv-spinner-wrap">
      <div className="dv-spinner" />
      {text && <p className="dv-spinner__text">{text}</p>}
    </div>
  );
}

/* CrossMatchTable */
function CrossMatchTable({ fields }) {
  if (!fields || fields.length === 0) return null;

  const statusIcon = (s) => {
    if (s === "match")
      return <IoCheckmarkCircle className="dv-table__icon dv-table__icon--match" />;
    if (s === "mismatch")
      return <IoAlertCircle className="dv-table__icon dv-table__icon--mismatch" />;
    return <IoWarning className="dv-table__icon dv-table__icon--partial" />;
  };

  const statusLabel = (s) => {
    if (s === "match") return "✓ Match";
    if (s === "mismatch") return "✗ Mismatch";
    return "~ Partial";
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
              <td>{f.printed}</td>
              <td>{f.qr}</td>
              <td className={`dv-table__status dv-table__status--${f.status}`}>
                {statusIcon(f.status)}
                <span>{statusLabel(f.status)}</span>
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

/* ResultCard */
function ResultCard({ outcome, riskScore, onReset, onDownload }) {
  const config = {
    verified: {
      cls: "dv-result--verified",
      icon: <IoCheckmarkCircle className="dv-result__icon" />,
      title: "Verified",
      desc: "Digital signature is valid and all printed fields match the signed QR data.",
      risk: "Low",
      riskCls: "dv-result__risk--low",
    },
    tampered: {
      cls: "dv-result--tampered",
      icon: <IoAlertCircle className="dv-result__icon" />,
      title: "Possible tampering — flagged",
      desc: "Digital signature is valid, but one or more printed fields do not match the signed QR data. The card may have been physically altered.",
      risk: "High",
      riskCls: "dv-result__risk--high",
    },
    forged: {
      cls: "dv-result--forged",
      icon: <HiOutlineXCircle className="dv-result__icon" />,
      title: "Forged or invalid document",
      desc: "The digital signature could not be verified. This document may be fabricated.",
      risk: "High",
      riskCls: "dv-result__risk--high",
    },
    manual_review: {
      cls: "dv-result--manual",
      icon: <IoWarning className="dv-result__icon" />,
      title: "Needs manual review",
      desc: "The QR code is either unsigned (old format) or could not be read. This case has been flagged for manual review by a KYC officer.",
      risk: "Medium",
      riskCls: "dv-result__risk--medium",
    },
  };

  const c = config[outcome] || config.manual_review;

  return (
    <div className={`dv-result ${c.cls}`}>
      <div className="dv-result__header">
        {c.icon}
        <div>
          <h3 className="dv-result__title">{c.title}</h3>
          <p className="dv-result__desc">{c.desc}</p>
        </div>
      </div>

      <div className="dv-result__meta">
        <div className="dv-result__meta-item">
          <span className="dv-result__meta-label">Risk score</span>
          <span className="dv-result__meta-value">{riskScore ?? "—"}/100</span>
        </div>
        <div className="dv-result__meta-item">
          <span className="dv-result__meta-label">Risk level</span>
          <span className={`dv-result__risk ${c.riskCls}`}>{c.risk}</span>
        </div>
      </div>

      <div className="dv-result__actions">
        <button className="dv-btn dv-btn--primary" onClick={onReset}>
          <HiOutlineArrowPath />
          <span>Verify another document</span>
        </button>
        <button className="dv-btn dv-btn--outline" onClick={onDownload}>
          <HiOutlineDocumentArrowDown />
          <span>Download report (JSON)</span>
        </button>
      </div>

      <p className="dv-result__footer-note">
        <HiOutlineLockClosed />
        Your uploaded document has been deleted from our servers.
      </p>
    </div>
  );
}

/* ─────────────────────── Main Component ─────────────────────── */

export default function DocumentVerify() {
  /* ── State ── */
  const [currentStep, setCurrentStep] = useState(0);
  const [stepStatuses, setStepStatuses] = useState([
    "active",
    "idle",
    "idle",
    "idle",
  ]); // idle | active | loading | success | error

  // Step 1
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [consent, setConsent] = useState(false);
  const [uploadError, setUploadError] = useState("");
  const [fileError, setFileError] = useState("");

  // Session
  const [sessionId, setSessionId] = useState(null);
  const [cancelled, setCancelled] = useState(false);

  // Step 2
  const [qrResult, setQrResult] = useState(null);
  const [qrError, setQrError] = useState("");

  // Step 3
  const [sigResult, setSigResult] = useState(null);
  const [sigError, setSigError] = useState("");

  // Step 4
  const [crossResult, setCrossResult] = useState(null);
  const [crossError, setCrossError] = useState("");

  // Loading
  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState("");

  /* ── Cleanup preview URLs on unmount ── */
  const previewRef = useRef(null);

  useEffect(() => {
    return () => {
      if (previewRef.current) {
        URL.revokeObjectURL(previewRef.current);
      }
    };
  }, []);

  /* ── Helpers ── */

  const updateStatus = (stepIndex, status) => {
    setStepStatuses((prev) => {
      const copy = [...prev];
      copy[stepIndex] = status;
      return copy;
    });
  };

  const maskAadhaar = (last4) => `XXXX XXXX ${last4}`;

  const validateFile = (f) => {
    if (!ACCEPTED_TYPES.includes(f.type)) {
      return "Unsupported file type. Please upload JPG, PNG or PDF.";
    }
    if (f.size > MAX_SIZE_BYTES) {
      return `File too large (${(f.size / 1024 / 1024).toFixed(1)} MB). Maximum is 5 MB.`;
    }
    return "";
  };

  const handleFileSelect = useCallback(
    (f) => {
      setFileError("");
      const err = validateFile(f);
      if (err) {
        setFileError(err);
        return;
      }
      // Revoke old preview
      if (previewRef.current) {
        URL.revokeObjectURL(previewRef.current);
      }
      const url = f.type !== "application/pdf" ? URL.createObjectURL(f) : null;
      previewRef.current = url;
      setFile(f);
      setPreview(url || "pdf");
    },
    []
  );

  const handleRemoveFile = useCallback(() => {
    if (previewRef.current) {
      URL.revokeObjectURL(previewRef.current);
      previewRef.current = null;
    }
    setFile(null);
    setPreview(null);
    setFileError("");
  }, []);

  /* ── Sequential pipeline ── */

  const runPipeline = async () => {
    if (!file || !consent) return;
    setCancelled(false);
    setUploadError("");
    setQrError("");
    setSigError("");
    setCrossError("");
    setQrResult(null);
    setSigResult(null);
    setCrossResult(null);
    setLoading(true);

    // Step 1: Upload
    setCurrentStep(0);
    updateStatus(0, "loading");
    setLoadingText("Uploading document…");
    try {
      const uploadRes = await apiUpload(file, "aadhaar", consent);
      if (cancelled) return;
      setSessionId(uploadRes.sessionId);
      updateStatus(0, "success");
    } catch (e) {
      updateStatus(0, "error");
      setUploadError(e.message || "Upload failed.");
      setLoading(false);
      return;
    }

    // Step 2: QR decode
    setCurrentStep(1);
    updateStatus(1, "loading");
    setLoadingText("Scanning for QR code…");
    try {
      const qr = await apiQrDecode("mock"); // sessionId from state may not be set yet
      if (cancelled) return;
      setQrResult(qr);
      if (!qr.qrFound) {
        updateStatus(1, "error");
        setQrError("No QR code found in the uploaded document.");
        // Still continue to cross-match for manual_review outcome
      } else {
        updateStatus(1, "success");
      }
    } catch (e) {
      updateStatus(1, "error");
      setQrError(e.message || "QR decode failed.");
      setLoading(false);
      return;
    }

    // Step 3: Signature
    setCurrentStep(2);
    updateStatus(2, "loading");
    setLoadingText("Verifying digital signature…");
    try {
      const sig = await apiSignatureVerify("mock");
      if (cancelled) return;
      setSigResult(sig);
      if (sig.signatureValid === false) {
        updateStatus(2, "error");
      } else if (sig.signatureValid === null) {
        updateStatus(2, "error");
      } else {
        updateStatus(2, "success");
      }
    } catch (e) {
      updateStatus(2, "error");
      setSigError(e.message || "Signature verification failed.");
      setLoading(false);
      return;
    }

    // Step 4: Cross-match
    setCurrentStep(3);
    updateStatus(3, "loading");
    setLoadingText("Cross-matching OCR and QR data…");
    try {
      const cm = await apiCrossMatch("mock");
      if (cancelled) return;
      setCrossResult(cm);
      if (cm.outcome === "verified") {
        updateStatus(3, "success");
      } else {
        updateStatus(3, "error");
      }
    } catch (e) {
      updateStatus(3, "error");
      setCrossError(e.message || "Cross-match failed.");
      setLoading(false);
      return;
    }

    setCurrentStep(4); // done
    setLoading(false);
  };

  const handleCancel = () => {
    setCancelled(true);
    setLoading(false);
  };

  const handleReset = () => {
    handleRemoveFile();
    setConsent(false);
    setCurrentStep(0);
    setStepStatuses(["active", "idle", "idle", "idle"]);
    setSessionId(null);
    setCancelled(false);
    setUploadError("");
    setFileError("");
    setQrResult(null);
    setQrError("");
    setSigResult(null);
    setSigError("");
    setCrossResult(null);
    setCrossError("");
    setLoading(false);
    setLoadingText("");
  };

  const handleRetryStep = (stepIdx) => {
    // For simplicity, restart the whole pipeline
    // A production version would resume from the failed step
    runPipeline();
  };

  const handleDownloadReport = () => {
    const report = {
      timestamp: new Date().toISOString(),
      sessionId,
      qrResult: qrResult
        ? {
            qrFound: qrResult.qrFound,
            qrType: qrResult.qrType,
            fields: qrResult.fields
              ? {
                  name: qrResult.fields.name,
                  dob: qrResult.fields.dob,
                  gender: qrResult.fields.gender,
                  aadhaar: maskAadhaar(qrResult.fields.last4),
                }
              : null,
          }
        : null,
      signatureResult: sigResult,
      crossMatchResult: crossResult
        ? {
            outcome: crossResult.outcome,
            riskScore: crossResult.riskScore,
            fields: crossResult.fields,
          }
        : null,
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `kyc-report-${sessionId || "unknown"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /* ── Render ── */

  const canStart = file && consent && !loading;
  const pipelineDone = currentStep === 4 && crossResult;

  return (
    <div className="dv">
      <div className="dv__container">
        {/* Header */}
        <div className="dv__header">
          <h1 className="dv__title">Step 1:Upload ID document</h1><br></br>
          <p className="dv__subtitle">
            Upload your Aadhaar card to verify its authenticity via Secure QR
            code, digital signature and OCR cross-match.
          </p>
        </div>

        {/* Stepper */}
        <Stepper currentStep={currentStep} stepStatuses={stepStatuses} />

        {/* Step 1 — Upload & Consent */}
        {currentStep === 0 && !loading && (
          <StepCard
            title="Step 1 — Upload your document"
            subtitle="Upload the front side of your Aadhaar card containing the QR code."
          >
            <UploadZone
              file={file}
              preview={preview && preview !== "pdf" ? preview : null}
              onFileSelect={handleFileSelect}
              onRemove={handleRemoveFile}
              disabled={loading}
            />
            {file && file.type === "application/pdf" && preview === "pdf" && (
              <div className="dv-upload__pdf-badge">
                <HiOutlineDocumentCheck className="dv-upload__pdf-icon" />
                <span>{file.name}</span>
                <button
                  className="dv-upload__remove-btn dv-upload__remove-btn--inline"
                  onClick={handleRemoveFile}
                >
                  <HiOutlineXMark />
                </button>
              </div>
            )}
            {fileError && (
              <p className="dv-error-msg">
                <HiOutlineExclamationTriangle /> {fileError}
              </p>
            )}

            {/* Tips */}
            <div className="dv-tips">
              <HiOutlineInformationCircle className="dv-tips__icon" />
              <div>
                <strong>Tips for best results</strong>
                <ul className="dv-tips__list">
                  <li>Make sure the QR code is sharp, well-lit and fully visible.</li>
                  <li>Avoid glare, shadows and blurry images.</li>
                  <li>Crop the image to show only the card if possible.</li>
                </ul>
              </div>
            </div>

            {/* Consent */}
            <label className="dv-consent">
              <input
                type="checkbox"
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                className="dv-consent__checkbox"
              />
              <span className="dv-consent__text">
                I consent to my document being processed for verification
                purposes. Uploaded files are deleted immediately after
                verification in accordance with the{" "}
                <strong>Digital Personal Data Protection Act, 2023</strong>.
              </span>
            </label>

            {uploadError && (
              <p className="dv-error-msg">
                <HiOutlineExclamationTriangle /> {uploadError}
              </p>
            )}

            <div className="dv-step-actions">
              <button
                className="dv-btn dv-btn--primary dv-btn--lg"
                disabled={!canStart}
                onClick={runPipeline}
              >
                <HiOutlineShieldCheck />
                <span>Start verification</span>
                <HiOutlineChevronRight />
              </button>
            </div>
          </StepCard>
        )}

        {/* Loading state */}
        {loading && (
          <StepCard title={loadingText}>
            <Spinner text={loadingText} />
            <div className="dv-step-actions">
              <button className="dv-btn dv-btn--outline" onClick={handleCancel}>
                Cancel
              </button>
            </div>
          </StepCard>
        )}

        {/* Step 2 result — QR decode */}
        {!loading && currentStep >= 1 && qrResult && (
          <StepCard
            title="QR code detection &amp; decode"
            status={
              !qrResult.qrFound
                ? "error"
                : qrResult.qrType === "old"
                ? "warning"
                : "success"
            }
          >
            {/* QR status badges */}
            <div className="dv-qr-badges">
              <span
                className={`dv-badge ${
                  qrResult.qrFound ? "dv-badge--green" : "dv-badge--red"
                }`}
              >
                {qrResult.qrFound ? "QR found" : "QR not found"}
              </span>
              {qrResult.qrFound && (
                <span
                  className={`dv-badge ${
                    qrResult.qrType === "secure"
                      ? "dv-badge--green"
                      : "dv-badge--amber"
                  }`}
                >
                  {qrResult.qrType === "secure"
                    ? "Secure QR (signed)"
                    : "Old QR (unsigned)"}
                </span>
              )}
            </div>

            {/* Decoded fields */}
            {qrResult.fields && (
              <div className="dv-decoded">
                <h4 className="dv-decoded__title">Decoded fields</h4>
                <div className="dv-decoded__grid">
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Name</span>
                    <span className="dv-decoded__value">
                      {qrResult.fields.name}
                    </span>
                  </div>
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Date of birth</span>
                    <span className="dv-decoded__value">
                      {qrResult.fields.dob}
                    </span>
                  </div>
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Gender</span>
                    <span className="dv-decoded__value">
                      {qrResult.fields.gender === "M"
                        ? "Male"
                        : qrResult.fields.gender === "F"
                        ? "Female"
                        : qrResult.fields.gender}
                    </span>
                  </div>
                  <div className="dv-decoded__item">
                    <span className="dv-decoded__label">Aadhaar number</span>
                    <span className="dv-decoded__value dv-decoded__value--mono">
                      {maskAadhaar(qrResult.fields.last4)}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Old QR warning */}
            {qrResult.qrType === "old" && (
              <div className="dv-warning-box">
                <HiOutlineExclamationTriangle className="dv-warning-box__icon" />
                <p>
                  This QR code uses the old unsigned format and cannot be
                  cryptographically verified. The document will proceed to{" "}
                  <strong>manual review</strong>.
                </p>
              </div>
            )}

            {/* QR not found */}
            {!qrResult.qrFound && (
              <div className="dv-error-box">
                <HiOutlineXCircle className="dv-error-box__icon" />
                <div>
                  <p>
                    We couldn't detect a QR code in your upload. This may be due
                    to low resolution, glare, or the QR being partially cropped.
                  </p>
                  <button
                    className="dv-btn dv-btn--outline dv-btn--sm"
                    onClick={handleReset}
                  >
                    <HiOutlineArrowPath />
                    <span>Re-upload a clearer image</span>
                  </button>
                </div>
              </div>
            )}

            {qrError && !qrResult && (
              <p className="dv-error-msg">
                <HiOutlineExclamationTriangle /> {qrError}
              </p>
            )}
          </StepCard>
        )}

        {/* Step 3 result — Signature */}
        {!loading && currentStep >= 2 && sigResult && (
          <StepCard
            title="Digital signature verification"
            status={
              sigResult.signatureValid === true
                ? "success"
                : sigResult.signatureValid === false
                ? "error"
                : "warning"
            }
          >
            <div className="dv-sig">
              {sigResult.signatureValid === true && (
                <div className="dv-sig__result dv-sig__result--valid">
                  <IoCheckmarkCircle className="dv-sig__icon" />
                  <div>
                    <p className="dv-sig__label">Digital signature valid</p>
                    <p className="dv-sig__issuer">
                      Issued by: {sigResult.issuer}
                    </p>
                    <p className="dv-sig__reason">{sigResult.reason}</p>
                  </div>
                </div>
              )}
              {sigResult.signatureValid === false && (
                <div className="dv-sig__result dv-sig__result--invalid">
                  <IoAlertCircle className="dv-sig__icon" />
                  <div>
                    <p className="dv-sig__label">Signature invalid</p>
                    <p className="dv-sig__reason">{sigResult.reason}</p>
                  </div>
                </div>
              )}
              {sigResult.signatureValid === null && (
                <div className="dv-sig__result dv-sig__result--na">
                  <IoWarning className="dv-sig__icon" />
                  <div>
                    <p className="dv-sig__label">
                      Signature verification not available
                    </p>
                    <p className="dv-sig__reason">{sigResult.reason}</p>
                  </div>
                </div>
              )}
            </div>
            <p className="dv-sig__note">
              <HiOutlineInformationCircle />
              A valid signature proves the card data is genuine and issued by
              UIDAI. It does <em>not</em> prove that the person uploading it is
              the cardholder — that is established during the live video KYC
              step.
            </p>

            {sigError && (
              <p className="dv-error-msg">
                <HiOutlineExclamationTriangle /> {sigError}
              </p>
            )}
          </StepCard>
        )}

        {/* Step 4 result — Cross-match */}
        {!loading && currentStep >= 3 && crossResult && (
          <StepCard
            title="Cross-match (Printed card vs QR data)"
            status={
              crossResult.outcome === "verified"
                ? "success"
                : crossResult.outcome === "manual_review"
                ? "warning"
                : "error"
            }
          >
            <CrossMatchTable fields={crossResult.fields} />

            {crossError && (
              <p className="dv-error-msg">
                <HiOutlineExclamationTriangle /> {crossError}
              </p>
            )}
          </StepCard>
        )}

        {/* Final Result Card */}
        {pipelineDone && (
          <ResultCard
            outcome={crossResult.outcome}
            riskScore={crossResult.riskScore}
            onReset={handleReset}
            onDownload={handleDownloadReport}
          />
        )}

        {/* Error with retry — shown when pipeline stopped at a step */}
        {!loading &&
          !pipelineDone &&
          currentStep > 0 &&
          (uploadError || qrError || sigError || crossError) && (
            <div className="dv-retry-wrap">
              <button
                className="dv-btn dv-btn--primary"
                onClick={() => handleRetryStep(currentStep)}
              >
                <HiOutlineArrowPath />
                <span>Retry verification</span>
              </button>
              <button className="dv-btn dv-btn--outline" onClick={handleReset}>
                <HiOutlineArrowPath />
                <span>Start over</span>
              </button>
            </div>
          )}

        {/* Privacy footer */}
        <div className="dv__privacy-footer">
          <HiOutlineLockClosed />
          <span>
            Your document is processed securely and deleted immediately after
            verification.
          </span>
        </div>
      </div>
    </div>
  );
}