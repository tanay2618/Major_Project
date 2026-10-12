import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { IoEye, IoEyeOff } from "react-icons/io5";
import { HiOutlineBolt } from "react-icons/hi2";
import "../styles/Register.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export default function Register() {
  const navigate = useNavigate();

  const [formData, setFormData] = useState({
    full_name: "",
    email: "",
    password: "",
    confirmPassword: "",
  });

  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setFormData({
      ...formData,
      [e.target.name]: e.target.value,
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (formData.password !== formData.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    if (formData.password.length < 6) {
      setError("Password must be at least 6 characters long.");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_BASE}/api/auth/register`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          full_name: formData.full_name,
          email: formData.email,
          password: formData.password,
          role: "applicant", // Always applicant — officers assigned manually in DB
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail || "Registration failed. Please try again."
        );
      }

      // Store session
      localStorage.setItem("kyc_token", data.access_token);
      localStorage.setItem("kyc_user", JSON.stringify(data.user));

      // Always go to Landing Page after register
      navigate("/");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="register-page">
      <div className="register-card">
        {/* Brand */}
        <div className="register-brand" onClick={() => navigate("/")}>
          <div className="register-brand__logo">
            <HiOutlineBolt size={20} color="#fff" />
          </div>
          <span className="register-brand__name">DeepTrust KYC</span>
        </div>

        <div className="register-header">
          <h1 className="register-title">Create an account</h1>
          <p className="register-subtitle">
            Join our intelligent, deepfake-resistant Video KYC platform
          </p>
        </div>

        {error && <div className="register-error">{error}</div>}

        <form onSubmit={handleSubmit} className="register-form">
          <div className="register-field">
            <label htmlFor="full_name">Full Name</label>
            <input
              type="text"
              id="full_name"
              name="full_name"
              placeholder="e.g. Rahul Sharma"
              value={formData.full_name}
              onChange={handleChange}
              required
              className="register-input"
            />
          </div>

          <div className="register-field">
            <label htmlFor="email">Email Address</label>
            <input
              type="email"
              id="email"
              name="email"
              placeholder="name@example.com"
              value={formData.email}
              onChange={handleChange}
              required
              className="register-input"
            />
          </div>

          <div className="register-field">
            <label htmlFor="password">Password</label>
            <div className="register-input-wrap">
              <input
                type={showPassword ? "text" : "password"}
                id="password"
                name="password"
                placeholder="Minimum 6 characters"
                value={formData.password}
                onChange={handleChange}
                required
                className="register-input"
              />
              <button
                type="button"
                className="register-eye-btn"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex="-1"
                title={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <IoEyeOff /> : <IoEye />}
              </button>
            </div>
          </div>

          <div className="register-field">
            <label htmlFor="confirmPassword">Confirm Password</label>
            <div className="register-input-wrap">
              <input
                type={showConfirmPassword ? "text" : "password"}
                id="confirmPassword"
                name="confirmPassword"
                placeholder="Re-enter password"
                value={formData.confirmPassword}
                onChange={handleChange}
                required
                className="register-input"
              />
              <button
                type="button"
                className="register-eye-btn"
                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                tabIndex="-1"
                title={
                  showConfirmPassword ? "Hide password" : "Show password"
                }
              >
                {showConfirmPassword ? <IoEyeOff /> : <IoEye />}
              </button>
            </div>
          </div>

          <button
            type="submit"
            className="register-submit-btn"
            disabled={loading}
          >
            {loading ? "Creating account..." : "Register Account"}
          </button>
        </form>

        <div className="register-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </div>
      </div>
    </div>
  );
}