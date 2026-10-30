# Wallet app compatibility

> Last updated: 2026-10-28

The EveryCRED wallet app (`EveryCRED/everycred-holder-wallet-app`) was
built against the DCS backend. This service serves the same endpoints
with the same paths, request bodies, status codes, messages, and
response shapes, so moving the app here only changes its base URL.

## What the app must change

| Setting | Value |
|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | `https://<holder service host>/v1` |
| `EXPO_PUBLIC_ASSET_BASE_URL` | No longer used for credentials: `credential_path` is now an absolute URL, which the app's `assetUrl()` passes through unchanged. Keep it for anything else that still reads from the DCS asset host. |

Nothing else changes: the app keeps sending only `Accept`,
`Content-Type: application/json`, and `Authorization: Bearer <token>`.
The token stays opaque to the app; it is now issued by this service.

Holders who registered on the DCS do not exist here yet, so they must
register again (or be migrated) before switching.

## Envelope

Every response is `{"status", "data", "message"}`, built by
`app/core/responses.py`:

- `status` is `"success"` for 200, 201, 202 and `"fail"` otherwise.
- Falsy `data` (`{}`, `[]`, `0`) becomes `null`, as in the DCS
  `StandardResponse`.
- Framework errors keep the DCS shape with the numeric status:
  missing bearer token `401 {"status": 401, "data": null, "message":
  "Not authenticated"}`, validation `422 {"status": 422, "data": null,
  "message": "<field> <msg>", "errors": [{"field", "message", "type"}]}`,
  unknown route `404 {"status": 404, ..., "message": "Not Found"}`.
- An invalid or expired token, or an ended session, is
  `401 {"status": "fail", "data": null, "message": "Invalid token"}`.
  The app logs the holder out after a second 401, so 401 is only used
  for a dead token.

## Endpoints

| # | Method | Path | Auth | Success | Implemented in |
|---|---|---|---|---|---|
| 1 | POST | `/v1/holder/validate` | none | 200 | `features/auth` |
| 2 | POST | `/v1/holder/login` | none | 200 | `features/auth` |
| 3 | GET | `/v1/holder` | bearer | 200 | `features/holders` |
| 4 | POST | `/v1/holder/recover` | none | 200 | `features/auth` |
| 5 | DELETE | `/v1/holder` | bearer | 200 | `features/auth` |
| 6 | POST | `/v1/holder/register` | none | 201 | `features/auth` |
| 7 | POST | `/v1/wallet/holder/otp/send` | none | 200 | `features/auth` |
| 8 | POST | `/v1/wallet/holder/otp/verify` | none | 200 | `features/auth` |
| 9 | POST | `/v1/holder/forget` | none | 200 | `features/auth` |
| 10 | POST | `/v1/holder/password/change` | bearer | 200 | `features/auth` |
| 11 | PUT | `/v1/holder/update` | bearer | 200 | `features/holders` |
| 12 | POST | `/v1/holder/storage` | bearer | 201 | `features/wallet_storage` |
| 13 | GET | `/v1/user/holder/credentials` | bearer | 200 | `features/credentials` |
| 14 | GET | `/v1/holder/credential/share` | bearer | 200 | `features/credentials` |
| 15 | GET | `/v1/holder/stats` | bearer | 200 | `features/credentials` |
| 16 | GET | `/v1/holder/credential/notification` | bearer | 200 | `features/credentials` |
| 17 | GET | `/v1/user/credential/{credential_unique_id}` | none | 200 | `features/credentials` |
| 18 | POST | `/v1/credential/verification/analytics?uuid=` | none | 201 | `features/credentials` |
| 19 | POST | `/v1/holder/logout` | bearer | 200 | `features/auth` |
| 20 | POST | `/v1/holder/login/sso?token=&sso_type=` | none | 200 | `features/auth` |
| — | POST | `/v1/holder/login/otp` | OTP login token | 200 | `features/auth` |
| 21 | POST | `/v1/holder/email/confirmation` | none | 200 | `features/auth` |
| 22 | PUT | `/v1/holder/email/verify?verify_token=` | none | 200 | `features/auth` |
| 23 | GET | `/v1/holder/credential/preview?cred_id=` | bearer | 200 | `features/credentials` |
| 24 | GET | `/v1/holder/credential/download?cred_id=` | bearer | 200 | `features/credentials` |
| 25 | POST | `/v1/holder/send/email?cred_id=` | bearer | 200 | `features/credentials` |
| 26 | GET | `/v1/holder/subject/requests` (and deprecated `/v1/subject/requests`) | bearer | 200 | `features/gateway` |
| 27 | GET | `/v1/holder/request/{request_id}` (and deprecated `/v1/request/{request_id}`) | bearer | 200 | `features/gateway` |
| 28 | POST | `/v1/holder/request/submission` (and deprecated `/v1/request/submission`) | bearer | 200 | `features/gateway` |
| — | POST | `/v1/holder/reset/{token}/submit` (form) | reset link | 200 | `features/auth` |
| — | PUT / DELETE | `/v1/push/holder/token` | bearer | 200 | `features/devices` |

The last two are not called by the app today but keep the DCS paths:
the first serves the web password reset page, the second is for push
notifications once the app adds them.

### Holder account (1–10)

- **Validate**: `{email}` or `{did}`; 200 "Holder validated
  successfully!" or 400 "DID or holder not found!".
- **Login**: `{email | did, password}`. 200 `{user_type: "holder",
  token, is_deleted: false}` "logged in successfully". Unknown holder
  404, wrong password 400, both "Email or Password is invalid". An
  account deleted less than `ACCOUNT_DELETION_GRACE_DAYS` ago returns
  200 `{is_deleted: true, token: <recovery token>}`; past the grace
  period 403 "This account is no longer recoverable…".
- **Recover**: `{recovery_token}`, valid `RECOVERY_TOKEN_TTL_SECONDS`
  (120). 200 `{user_type, token}` "Your account has been successfully
  recovered!"; 400 for an expired, forged, or unusable token.
- **Delete**: soft delete; ends every session and push token; 200
  "Holder deleted successfully!".
- **Register**: `{name, email, password, confirm_password, contact?}`,
  DCS patterns, unknown fields allowed. 201 with `data: null`.
- **OTP send / verify**: `{email, otp_type: "email"}` and
  `{email, otp_code, otp_type}`. 6-digit codes, 2-minute expiry,
  3 attempts by default. Wrong codes answer 400 with
  `data: {remaining_attempts, max_attempts}`. A successful verify also
  returns `login_token` (new, additive); apps that ignore it keep
  working.
- **Forget**: always 200 with the same message.
- **Password change**: `{current_password, new_password,
  confirm_password}`; 200 with the profile, `contact` named
  `phone_number` as in the DCS.

### Profile (3, 11)

`GET /v1/holder` returns the DCS keys: `id` (integer, see below),
`uuid`, `digi_client_id` (null), `name`, `email`, `profile_image`
(absolute URL or null), `login_type` ("register"), `did`,
`qrcode_path`, `holder_profile_path`, `is_kyc`, `is_terms_accepted`,
`status` ("registered"), `created_at`, `updated_at` (naive ISO-8601),
`deleted_at`, `contact`. `PUT /v1/holder/update` takes `{name?,
contact?, profile_image?}` with the image as raw base64.

### Credentials (13–18)

Credentials are fetched live through the connector and never stored.

- **List**: `holder_id` must be the caller's `id` (else 403 "You can
  only view your own credentials."); `type` is `issued`, `revoked` or
  `expired`; rows newest first; `data: {data, pages: <page>, total}`;
  an empty bucket is **404** "Details not found!" with
  `data: {data: [], pages, total: 0}`, which the app relies on.
  `per_page=0` returns a plain list.
- **Share**: `{name, viewer_link, qr_image, is_verifiable,
  download_link, logo_image, subject_name}`; `viewer_link` is
  `VERIFIER_BASE_URL` + the credential's unique id.
- **Stats**: the issuing DCS's answer, passed through.
- **Notifications**: one "issued" item per credential and a "revoked"
  item for revoked ones, newest first.
- **Public lookup** and **verification analytics**: no token; routed by
  the credential's unique id through the connector.

### Sessions, social sign-in and email (19–22)

- **Logout**: ends the session of the token used; that token answers
  401 afterwards, push tokens registered from the device stop, other
  devices stay signed in. 200 "You have been logged out successfully.".
- **SSO**: `sso_type=gmail` only, `token` is a Google ID token whose
  audience is one of `GOOGLE_CLIENT_IDS` and whose email is verified.
  Signs in the existing account with that email: 200 `{token,
  role_type: "holder"}` "logged in successfully". No account: 404
  "Please register!". Anything else: 400 "Invalid token". The body is
  accepted and ignored.
- **Email confirmation**: `{email}`; always 200 "Email sent
  successfully!" with `data: null`; a link to `EMAIL_VERIFICATION_URL`
  is emailed only when the account exists.
- **Email verify**: 200 `{holder_email_status: "verified"}` "Email
  verified successfully!"; 400 "Invalid token" otherwise.

### Credential actions (23–25)

- **Preview**: `{valid_from, valid_until, revoked, verification_count,
  subject_name, logo_image, credential_data: [{fname, fvalue,
  ftype}]}`, message "Credential preview fetched successfully!".
- **Download**: `{credential: <URL of the credential document>}`,
  message "Credential downloaded successfully!".
- **Send email**: `{holder_email: [...]}`, at most
  `MAX_SHARE_RECIPIENTS` addresses; each gets the credential's name,
  issuer, unique id and verifier link. 200 "Email sent successfully!";
  400 "Failed to send mail" if delivery fails.

### Credential requests (26–28)

Requests live in the DCS that sent them. The list merges every source
the holder is linked to, newest first, and adds `source_code` to each
item; the rest of each item is the DCS's own.

- **List**: `page` (1), `size` (10, at most 100), `search` (subject
  name, issuer name or request id); `{subjects, total, page, size,
  pages}`. The deprecated path returns `{subjects, total}` unpaged.
- **Get**: the DCS's request detail plus `source_code`; 404 "Request
  not found." when no linked source has it.
- **Submission**: `{request_id, slug, digilocker_id?}`, sent unchanged
  to the request's own source; its status and message are passed on.

## Integer ids

The app sends back integers it received: `holder_id` (the profile `id`)
and `cred_id` (a credential row's `id`).

- `holders.numeric_id` is a random positive integer below 2^52, so it
  is safe in JavaScript and reveals nothing about row counts.
- `credential_refs` gives each (source, credential) pair a holder sees
  its own random integer. It stores references only. `cred_id` is
  resolved through it, scoped to the signed-in holder, so another
  holder's id answers 404.

## Intentional differences from the DCS

| Area | DCS | Here | Why |
|---|---|---|---|
| Error messages | Four paths returned the generic "Woops…" because the message constants did not exist (register password mismatch, password unchanged, unsupported image, missing subject) | Specific messages | The app shows `message` to the user |
| Unsupported profile image | 400 generic | 422 "Image format not supported…" | Same reason |
| Session checks | Password change, notifications and storage checked only the JWT signature | Every authenticated route checks the session and the account | Ended sessions and deleted accounts are refused everywhere |
| Register | No server-side OTP check | Requires an OTP verification of that email in the last `REGISTRATION_TOKEN_MINUTES`, used once | The DCS relied on the app; the app already verifies first, so its flow is unchanged |
| OTP send email failure | 200 (error only printed) | 502 with a message | A holder who never gets the code needs to know |
| Sign-in after registering | Separate password login | Optional `POST /v1/holder/login/otp` with the `login_token` from OTP verify | Lets the app skip the password prompt; `/holder/login` still works |
| OTP resend | No cooldown | 429 within `OTP_RESEND_COOLDOWN_SECONDS` | Limits email abuse |
| Mobile OTP | Kaleyra SMS | 400 "Mobile OTP is not supported…" | The app only uses email OTP |
| Login lockout | None | 429 after `LOGIN_MAX_FAILED_ATTEMPTS` wrong passwords | Brute-force protection |
| Storage with one date | 500 | Missing end gets the default window | Bug fix |
| Storage window | Unlimited | At most `PRESENTATION_MAX_WINDOW_SECONDS` (7 days) | S3 presigned URL limit |
| Empty notifications | 404 "Notifications not found!" (shown as an error toast) | 200 with an empty list | The app handles an empty list correctly |
| Notification items | `type`, `credential_image`, `issued_at`/`revoked_at` | The same plus `credential`, `issuer_name`, `created_at` | The app reads those keys and showed blanks |
| Validate without email or DID | 200 with body `null` | 400 "Email or DID required" | Consistent envelope |
| Public DID profile document | Included name, image and contact | Name and image only, rewritten when the image changes | The document is public; the phone number is personal data |
| Logout | Blacklisted the token | Ends the session, which revokes the token | Sessions are already checked on every request |
| SSO | gmail, linkedin, office365; office365 took the email from the body unchecked; created accounts | gmail only, existing accounts only | Accepting an unchecked email lets anyone sign in as anyone; LinkedIn needs a web redirect |
| Email confirmation | 404 for unknown emails; returned `verify_link` in the response | Always 200, link only emailed | Returning the link proved nothing, and the 404 revealed accounts |
| Email verify bad token | 401 | 400 | The app signs out after a second 401 |
| Preview `ftype` | The subject field type; fields without one omitted | `text` for every field | The connector carries values, not types |
| Preview `verification_count` | Count from the DCS row | `null` | Served by `/v1/holder/stats` |
| Download | Copied the file to `download/<holder>/json/` and linked that | Links the issuing DCS's document | Nothing about a credential is stored here |
| Send email | HTML template, unlimited recipients | Plain text, at most `MAX_SHARE_RECIPIENTS` | Same mailer as OTPs; bounds spam through an account |
| Request list | One DCS | Every linked DCS, each item with `source_code`; at most 100 per source | The connector forwards no paging yet |
| Holder rows in the list | Every `credential` column | The columns the app reads plus `uuid`, `source_code`, hashes and URLs; other DCS columns are absent | No credential data is stored here |

## Known gaps

- `GET /v1/holder/invited` and `POST /v1/holder/invited/{holder_uuid}/resend`
  are not served here. They sit in the DCS wallet module but are issuer
  routes: the issuer portal calls them with an issuer token to pick and
  re-invite holders of its organization. This service has no issuer
  accounts or organizations, so they stay in the DCS.

- `GET /v1/holder/stats` accepts `page` and `per_page`, but the
  connector's holder operations do not forward query parameters yet, so
  the source's default page is returned.
- The connector routes credentials by the id DCS sources put in their
  events. The public lookup and analytics routes look up by the
  credential's **unique id**, so DCS events must use
  `credential_unique_id` as `credential_id` (the DCS public verifier
  endpoint is also keyed by it).
- Issue and revoke times come from the connector (`first_seen_at`,
  `status_changed_at`): credentials issued before the connector started
  receiving events have the time they were first routed.
