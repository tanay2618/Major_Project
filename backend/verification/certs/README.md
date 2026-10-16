# UIDAI certificates

The server tries every `.cer` file in this folder when checking the Secure QR signature,
because UIDAI rotates its keys and older cards were signed with older keys.

Currently included:

- `uidai_offline_publickey_2026.cer` — downloaded by the project owner from UIDAI (valid 2026-02-03 to 2029-02-03).

Cards issued earlier may be signed with older keys. Download those yourself from UIDAI's official
"Data and Downloads" page (look for "Paperless Offline e-KYC" / "Secure QR Code") and drop them here:
https://uidai.gov.in/en/data-and-download

Do not download certificates from any other website, and do not commit anything you did not get from UIDAI.
Expired certificates are still accepted for old cards (the result carries a note), but a signature that
matches no certificate is treated as forged only for cards whose QR is a signed Secure QR.

NOT for this folder: encryption certificates (e.g. "Pre-Prod Encryption"), staging/auth certificates
(e.g. "Auth_Private_Key", "uidai_auth_sign_Prod") — those are for the Aadhaar Authentication API, not QR signatures.

If this folder has no certificates, signature checks return "cannot be checked" and every
Secure QR document goes to manual review instead of being verified.
