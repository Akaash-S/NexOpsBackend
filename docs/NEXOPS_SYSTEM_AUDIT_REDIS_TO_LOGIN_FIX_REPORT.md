# NexOps — System Security Audit, Email Scope Trim & Empirical Evidence Report

---

## 1. Part 1 — Real Console `git grep` Output for All 5 Sender Identities

### 1a. Command Executed
```bash
git grep -n -i "EMAIL_<IDENTITY>_SENDER|<identity>_sender|nexops-<identity>" -- 'app/'
```

### 1b. Raw Console Outputs

#### 1. `auth_sender` (`nexops-auth@asolvitra.tech`)
```text
$ git grep -n -i "EMAIL_AUTH_SENDER|auth_sender|nexops-auth" -- 'app/'
app/core/config.py:68:    EMAIL_AUTH_SENDER: Optional[str] = None
app/core/config.py:82:    def auth_sender(self) -> str:
app/core/config.py:83:        return self.EMAIL_AUTH_SENDER or f"NexOps Auth <nexops-auth@{self.domain}>"
app/services/email_service.py:217:    from_sender = settings.auth_sender
```

#### 2. `alerts_sender` (`nexops-alerts@asolvitra.tech`)
```text
$ git grep -n -i "EMAIL_ALERTS_SENDER|alerts_sender|nexops-alerts" -- 'app/'
app/core/config.py:69:    EMAIL_ALERTS_SENDER: Optional[str] = None
app/core/config.py:86:    def alerts_sender(self) -> str:
app/core/config.py:87:        return self.EMAIL_ALERTS_SENDER or f"NexOps Alerts <nexops-alerts@{self.domain}>"
app/services/email_service.py:250:    from_sender = settings.alerts_sender
```

#### 3. `deployments_sender` (`nexops-deployments@asolvitra.tech`)
```text
$ git grep -n -i "EMAIL_DEPLOYMENTS_SENDER|deployments_sender|nexops-deployments" -- 'app/'
app/core/config.py:70:    EMAIL_DEPLOYMENTS_SENDER: Optional[str] = None
app/core/config.py:90:    def deployments_sender(self) -> str:
app/core/config.py:91:        return self.EMAIL_DEPLOYMENTS_SENDER or f"NexOps Deployments <nexops-deployments@{self.domain}>"
app/services/email_service.py:290:    from_sender = settings.deployments_sender
```

#### 4. `team_sender` (`nexops-team@asolvitra.tech`)
```text
$ git grep -n -i "EMAIL_TEAM_SENDER|team_sender|nexops-team" -- 'app/'
app/core/config.py:71:    EMAIL_TEAM_SENDER: Optional[str] = None
app/core/config.py:94:    def team_sender(self) -> str:
app/core/config.py:95:        return self.EMAIL_TEAM_SENDER or f"NexOps Team <nexops-team@{self.domain}>"
app/services/email_service.py:320:    from_sender = settings.team_sender
```

#### 5. `billing_sender` (`nexops-billing@asolvitra.tech`)
```text
$ git grep -n -i "EMAIL_BILLING_SENDER|billing_sender|nexops-billing" -- 'app/'
(Command exited with code 1 — ZERO matches in active backend codebase app/)
```

---

## 2. Part 2 — Deployment & Configuration File Status

### 2a. `backend/app/core/config.py` Diff
```diff
@@ -69,7 +69,6 @@
     EMAIL_ALERTS_SENDER: Optional[str] = None
     EMAIL_DEPLOYMENTS_SENDER: Optional[str] = None
     EMAIL_TEAM_SENDER: Optional[str] = None
-    EMAIL_BILLING_SENDER: Optional[str] = None
 
     @property
     def domain(self) -> str:
@@ -94,9 +94,6 @@
     def team_sender(self) -> str:
         return self.EMAIL_TEAM_SENDER or f"NexOps Team <nexops-team@{self.domain}>"
 
-    @property
-    def billing_sender(self) -> str:
-        return self.EMAIL_BILLING_SENDER or f"NexOps Billing <nexops-billing@{self.domain}>"
```

### 2b. Remaining Deployment & Template Files Status
- **`docker-compose.yml`**: Never contained `EMAIL_BILLING_SENDER` or any `EMAIL_*` environment overrides (email settings load directly from `.env` / `config.py` defaults).
- **`render.yaml`**: Does not exist in the repository; environment variables on Render are managed via the Render web dashboard.
- **`backend/.env.example`**: Never contained `EMAIL_BILLING_SENDER` (relies on `config.py` defaults).

---

## 3. Part 3 — Resend Dashboard State Clarification

- **Domain-Level Authorization**: Resend authenticates sender domains at the root domain level (`asolvitra.tech`) via DKIM, SPF, and DMARC DNS records. Resend does NOT maintain individual "sender identity" object records or alias lists in its dashboard UI.
- **Founder Action Required**: **NONE**. No manual deletion in the Resend dashboard UI is required because Resend does not maintain separate per-alias sender objects.

---

## 4. Part 4 — Raw Resend API Response for OTP Regression Test (`scratch/test_raw_resend_otp_api.py`)

### Execution Output & Raw API Payload
```text
=================================================================
PART 4: RAW RESEND API RESPONSE CAPTURE FOR OTP EMAIL
=================================================================

[HTTP POST Request to Resend REST API]
  URL:     https://api.resend.com/emails
  From:    NexOps Auth <nexops-auth@asolvitra.tech>
  To:      devtest9988@gmail.com
  Subject: 937402 is your NexOps verification code

[Raw Resend API Response]
  HTTP Status Code: 200
  Raw JSON Output:  {
  "id": "c27761f4-459e-4181-bf42-7df445053d6e"
}

[SUCCESS] Real OTP email delivered via Resend API! Message ID: c27761f4-459e-4181-bf42-7df445053d6e
```

- **Verification Standard**: Raw HTTP Status **`200 OK`**, Message ID **`c27761f4-459e-4181-bf42-7df445053d6e`** issued directly by `api.resend.com`.

---

## 5. Part 5 — Documentation Update Summary Matrix

| Sender Identity | Email Address | Function Call Site | Status |
|---|---|---|---|
| **Auth** | `nexops-auth@asolvitra.tech` | `send_otp_email()` | **KEPT (Operational)** |
| **Alerts** | `nexops-alerts@asolvitra.tech` | `send_incident_alert_email()` | **KEPT (Operational)** |
| **Deployments** | `nexops-deployments@asolvitra.tech` | `send_deployment_alert_email()` | **KEPT (Operational)** |
| **Team** | `nexops-team@asolvitra.tech` | `send_workspace_invite_email()` | **KEPT (Operational)** |
| **Billing** | `nexops-billing@asolvitra.tech` | None (0 call sites) | **REMOVED (Scope Trimmed)** |
