import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  HiOutlineDocumentText, 
  HiOutlineDevicePhoneMobile, 
  HiOutlineCalendarDays, 
  HiOutlineVideoCamera,
  HiArrowRight,
  HiOutlineBolt
} from 'react-icons/hi2';
import { FiLogOut } from 'react-icons/fi';
import '../styles/Applicant.css';

const STEPS = [
  {
    id: 1,
    tag: 'Step 1',
    title: 'Upload ID document',
    description: 'Submit your Aadhaar or PAN card. Our AI runs instant OCR, quality checks, and basic tamper detection.',
    icon: HiOutlineDocumentText,
    color: 'blue',
    duration: '~1 min'
  },
  {
    id: 2,
    tag: 'Step 2',
    title: 'Verify with OTP',
    description: 'Confirm ownership of your registered mobile number to secure the session before we go live.',
    icon: HiOutlineDevicePhoneMobile,
    color: 'purple',
    duration: '~30 sec'
  },
  {
    id: 3,
    tag: 'Step 3',
    title: 'Request live meeting',
    description: 'Book a slot with a certified KYC officer. Humans stay in the loop — no auto-approvals.',
    icon: HiOutlineCalendarDays,
    color: 'orange',
    duration: 'Instant queue'
  },
  {
    id: 4,
    tag: 'Step 4',
    title: 'Complete live video KYC',
    description: 'Face the camera briefly. Our 4-signal AI (Deepfake, Liveness, Injection, Face Match) verifies you.',
    icon: HiOutlineVideoCamera,
    color: 'green',
    duration: '~2 min'
  },
];

export default function Applicant() {
  const navigate = useNavigate();
  const [user, setUser] = useState({ name: 'Applicant' });
  const [navLine, setNavLine] = useState({ left: 0, width: 0, opacity: 0 });
  const activeLinkRef = useRef(null);

  useEffect(() => {
    // Check for user in localStorage to protect the route
    const saved = localStorage.getItem('kyc_user');
    if (!saved) {
      navigate('/login');
      return;
    }
    try {
      setUser(JSON.parse(saved));
    } catch {
      navigate('/login');
    }
  }, [navigate]);

  useEffect(() => {
    if (activeLinkRef.current) {
      setNavLine({
        left: activeLinkRef.current.offsetLeft,
        width: activeLinkRef.current.offsetWidth,
        opacity: 1,
      });
    }
  }, []);

  const handleNavHover = (e) => {
    const el = e.currentTarget;
    setNavLine({ left: el.offsetLeft, width: el.offsetWidth, opacity: 1 });
  };

  const handleNavLeave = () => {
    if (activeLinkRef.current) {
      setNavLine({
        left: activeLinkRef.current.offsetLeft,
        width: activeLinkRef.current.offsetWidth,
        opacity: 1,
      });
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('kyc_user');
    navigate('/login');
  };

  // This correctly redirects to the Document Verify page we just built
  const handleGetStarted = () => {
    navigate('/applicant/document');
  };

  const firstName = (user.name || user.email || 'User').split(' ')[0].split('@')[0];

  return (
    <div className="applicant">
      {/* Header */}
      <header className="app-header">
        <div className="app-header__container">
          <div className="app-header__left" onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>
            <div className="app-header__logo" />
            <span className="app-header__brand">VerifyKYC</span>
          </div>

          <nav className="app-header__nav" onMouseLeave={handleNavLeave}>
            <button ref={activeLinkRef} className="app-header__link app-header__link--active" onMouseEnter={handleNavHover}>
              Overview
            </button>
            <button className="app-header__link" onMouseEnter={handleNavHover}>Verification</button>
            <button className="app-header__link" onMouseEnter={handleNavHover}>History</button>
            <button className="app-header__link" onMouseEnter={handleNavHover}>Help</button>
            <div className="app-header__sliding-line" style={{ left: navLine.left, width: navLine.width, opacity: navLine.opacity }} />
          </nav>

          <div className="app-header__right">
            <div className="app-header__avatar">{firstName.charAt(0).toUpperCase()}</div>
            <span className="app-header__user">{firstName}</span>
            <button className="app-header__logout" onClick={handleLogout} title="Logout">
              <FiLogOut />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="app-main">
        
        {/* Hero */}
        <section className="app-hero">
          <h1 className="app-hero__title">
            Welcome, {firstName}. <br/>
            <span className="gradient-text">Verify your identity in 4 steps.</span>
          </h1>
          <p className="app-hero__subtitle">
            Faster than a bank visit. Safer than a phone call. Complete your KYC 
            using our multi-signal AI verification pipeline.
          </p>
        </section>

        {/* Steps Grid */}
        <section className="steps-grid">
          {STEPS.map((step) => {
            const Icon = step.icon;
            return (
              <article key={step.id} className={`step-tile step-tile--${step.color}`}>
                <div className="step-tile__num">Step {step.id}</div>
                
                <div className={`step-tile__icon step-tile__icon--${step.color}`}>
                  <Icon />
                </div>

                <div className="step-tile__body">
                  <span className="step-tile__tag">{step.tag}</span>
                  <h2 className="step-tile__title">{step.title}</h2>
                  <p className="step-tile__desc">{step.description}</p>
                </div>

                <div className="step-tile__footer">
                  <span className="step-tile__duration">
                    <HiOutlineBolt /> {step.duration}
                  </span>
                </div>
              </article>
            );
          })}
        </section>

        {/* Get Started CTA */}
        <section className="start-panel">
          <div className="start-panel__glow" />
          <div className="start-panel__text">
            <h2>Ready to begin your verification?</h2>
            <p>We'll guide you through each step. Your data is encrypted end-to-end.</p>
          </div>
          <button className="start-panel__btn" onClick={handleGetStarted}>
            Get Started <HiArrowRight />
          </button>
        </section>

      </main>
    </div>
  );
}