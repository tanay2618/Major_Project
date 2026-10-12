import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import LandingPage from './pages/LandingPage.jsx';
import Login from './pages/Login.jsx';
import Register from './pages/Register.jsx';
import Applicant from './pages/Applicant.jsx';
import DocumentVerify from "./pages/DocumentVerify";


function OfficerQueue() {
  return (
    <div style={{ padding: 40, fontFamily: 'system-ui' }}>
      <h2>Officer queue</h2>
    </div>
  );
}

function DocumentPlaceholder() {
  return (
    <div style={{ padding: 40, fontFamily: 'system-ui', maxWidth: 640 }}>
      <h2>Step 1 — Document upload</h2>
      <p>Next we will build the real Aadhaar/PAN upload page here.</p>
      <a href="/applicant">← Back to overview</a>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* First page after npm run dev */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/applicant" element={<Applicant />} />
        <Route path="/applicant/document" element={<DocumentVerify />} />
        <Route path="/officer/queue" element={<OfficerQueue />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}