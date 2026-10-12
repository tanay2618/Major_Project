import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import {
  HiOutlineCpuChip,
  HiOutlineSignal,
  HiOutlineHeart,
  HiOutlineIdentification,
  HiArrowRight,
} from 'react-icons/hi2';
import '../styles/LandingPage.css';

export default function LandingPage() {
  const [navLine, setNavLine] = useState({ left: 0, width: 0, opacity: 0 });
  const activeLinkRef = useRef(null);

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
    setNavLine({
      left: el.offsetLeft,
      width: el.offsetWidth,
      opacity: 1,
    });
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

  return (
    <div className="landing">
      <header className="lp-header">
        <div className="lp-header__container">
          <div className="lp-header__left">
            <Link to="/" className="lp-header__brand">
              <div className="lp-header__logo" />
              <span>VerifyKYC</span>
            </Link>

            <nav className="lp-header__nav" onMouseLeave={handleNavLeave}>
              <a
                href="#platform"
                ref={activeLinkRef}
                className="lp-header__link lp-header__link--active"
                onMouseEnter={handleNavHover}
              >
                Platform
              </a>
              <a
                href="#architecture"
                className="lp-header__link"
                onMouseEnter={handleNavHover}
              >
                Architecture
              </a>
              <a
                href="#security"
                className="lp-header__link"
                onMouseEnter={handleNavHover}
              >
                Security
              </a>
              <a
                href="#start"
                className="lp-header__link"
                onMouseEnter={handleNavHover}
              >
                Get started
              </a>

              <div
                className="lp-header__sliding-line"
                style={{
                  left: navLine.left,
                  width: navLine.width,
                  opacity: navLine.opacity,
                }}
              />
            </nav>
          </div>

          <div className="lp-header__right">
            <Link to="/login" className="lp-header__signin">
              Sign in
            </Link>
            {/* Top-right CTA → Applicant 4-step overview */}
            <Link to="/applicant" className="lp-header__cta">
              Start verifying
            </Link>
          </div>
        </div>
      </header>

      <main>
        {/* HERO */}
        <section className="lp-hero" id="platform">
          <div className="lp-hero__container">
            <div className="lp-hero__content">
              <h1 className="lp-hero__title">
                The <span className="lp-hero__highlight">intelligent</span>
                <br />
                KYC platform for
                <br />
                <span className="lp-hero__highlight">global</span> businesses
              </h1>

              <p className="lp-hero__subtitle">
                AI-native Video KYC that blocks deepfakes, replays, and stream
                injection — with officers in control of the final decision.
              </p>

              <div className="lp-hero__actions">
                <Link to="/register" className="lp-btn lp-btn--primary">
                  Create free account
                </Link>
                <Link to="/login" className="lp-btn lp-btn--ghost">
                  Sign in
                </Link>
              </div>
            </div>

            <div className="lp-hero__visual">
              <div className="mock-ui">
                <div className="mock-ui__header">
                  <div className="mock-ui__dots">
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="mock-ui__url">verifykyc · live session</div>
                </div>

                <div className="mock-ui__body">
                  <div className="mock-ui__video">
                    <div className="mock-ui__scan" />
                    <div className="mock-ui__face" />
                  </div>

                  <div className="mock-ui__side">
                    <div className="risk-panel">
                      <div className="risk-panel__top">
                        <span className="risk-panel__label">Live risk score</span>
                        <span className="risk-panel__badge">Low risk</span>
                      </div>

                      <div className="risk-panel__score-row">
                        <div className="risk-panel__score">12</div>
                        <div className="risk-panel__score-meta">
                          <span className="risk-panel__out-of">/ 100</span>
                          <span className="risk-panel__status">Session healthy</span>
                        </div>
                      </div>

                      <div className="risk-panel__meter">
                        <div
                          className="risk-panel__meter-fill"
                          style={{ width: '12%' }}
                        />
                      </div>

                      <div className="risk-panel__divider" />
                      <p className="risk-panel__signals-title">Signal status</p>

                      <ul className="risk-panel__signals">
                        <li className="risk-signal">
                          <div className="risk-signal__left">
                            <span className="risk-signal__dot risk-signal__dot--ok" />
                            <div>
                              <span className="risk-signal__name">rPPG liveness</span>
                              <span className="risk-signal__hint">Pulse detected</span>
                            </div>
                          </div>
                          <span className="risk-signal__val">Pass</span>
                        </li>
                        <li className="risk-signal">
                          <div className="risk-signal__left">
                            <span className="risk-signal__dot risk-signal__dot--ok" />
                            <div>
                              <span className="risk-signal__name">CNN deepfake</span>
                              <span className="risk-signal__hint">Face authentic</span>
                            </div>
                          </div>
                          <span className="risk-signal__val">Pass</span>
                        </li>
                        <li className="risk-signal">
                          <div className="risk-signal__left">
                            <span className="risk-signal__dot risk-signal__dot--ok" />
                            <div>
                              <span className="risk-signal__name">Injection</span>
                              <span className="risk-signal__hint">Hardware stream</span>
                            </div>
                          </div>
                          <span className="risk-signal__val">Pass</span>
                        </li>
                        <li className="risk-signal">
                          <div className="risk-signal__left">
                            <span className="risk-signal__dot risk-signal__dot--ok" />
                            <div>
                              <span className="risk-signal__name">ArcFace match</span>
                              <span className="risk-signal__hint">ID match 0.91</span>
                            </div>
                          </div>
                          <span className="risk-signal__val">Pass</span>
                        </li>
                      </ul>

                      <div className="risk-panel__footer">
                        <span className="risk-panel__pulse" />
                        Live · updating every 2s
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* 4-SIGNAL CARDS */}
        <section className="lp-section" id="architecture">
          <div className="lp-section__inner">
            <p className="lp-section__eyebrow">Detection stack</p>
            <h2 className="lp-section__title">The 4-signal fraud engine</h2>
            <p className="lp-section__sub">
              Four independent checks. One clear risk score for the officer.
            </p>

            <div className="lp-cards">
              <article className="lp-card lp-card--orange">
                <div className="lp-card__icon">
                  <HiOutlineCpuChip />
                </div>
                <h3 className="lp-card__title">CNN deepfake</h3>
                <p className="lp-card__text">
                  Catch face swaps and synthetic faces in live video
                </p>
                <span className="lp-card__cta">
                  Primary signal <HiArrowRight />
                </span>
              </article>

              <article className="lp-card lp-card--purple">
                <div className="lp-card__icon">
                  <HiOutlineSignal />
                </div>
                <h3 className="lp-card__title">Stream injection</h3>
                <p className="lp-card__text">
                  Block virtual cams and OBS-style stream injects
                </p>
                <span className="lp-card__cta">
                  Integrity check <HiArrowRight />
                </span>
              </article>

              <article className="lp-card lp-card--blue">
                <div className="lp-card__icon">
                  <HiOutlineHeart />
                </div>
                <h3 className="lp-card__title">rPPG liveness</h3>
                <p className="lp-card__text">
                  Detect pulse from skin — stop photo and replay attacks
                </p>
                <span className="lp-card__cta">
                  Liveness <HiArrowRight />
                </span>
              </article>

              <article className="lp-card lp-card--teal">
                <div className="lp-card__icon">
                  <HiOutlineIdentification />
                </div>
                <h3 className="lp-card__title">Face–ID match</h3>
                <p className="lp-card__text">
                  Match live face to the ID portrait with ArcFace
                </p>
                <span className="lp-card__cta">
                  Identity bind <HiArrowRight />
                </span>
              </article>
            </div>
          </div>
        </section>

        {/* FINAL CTA */}
        <section className="lp-final" id="security">
          <div className="lp-final__inner" id="start">
            <p className="lp-final__eyebrow">For compliance teams</p>
            <h2 className="lp-final__title">
              Explainable risk. Human final decision.
            </h2>
            <p className="lp-final__text">
              Live scores, per-signal reasons, and officer Approve / Reject —
              built for real Video KYC demos.
            </p>
            <div className="lp-final__actions">
              {/* Bottom Get started → Applicant 4-step overview */}
              <Link to="/applicant" className="lp-btn lp-btn--light">
                Get started
              </Link>
              <Link to="/login" className="lp-final__link">
                Explore officer flow <HiArrowRight />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-footer__inner">
          <div className="lp-footer__brand">
            <div className="lp-header__logo" />
            <span>VerifyKYC</span>
          </div>
          <p>© 2026 VerifyKYC · Deepfake-resistant Video KYC</p>
        </div>
      </footer>
    </div>
  );
}