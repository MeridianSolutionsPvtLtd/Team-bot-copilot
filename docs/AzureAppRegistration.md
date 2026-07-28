# Azure App Registration & Policy Setup Guide

This document describes how to configure Microsoft Entra ID (Azure AD) and Microsoft Teams policies to allow the webhook to listen to and download meeting transcripts.

---

## 1. Microsoft Entra ID App Registration

1. Go to the [Microsoft Entra admin center](https://entra.microsoft.com/) as an administrator.
2. Navigate to **Identity > Applications > App registrations** and click **New registration**.
3. Provide a name (e.g. `MeridianTeamsMeetingIntelligence`).
4. Select **Supported account types** (e.g., *Accounts in this organizational directory only - Single tenant*).
5. Click **Register**.

### 2. Client Secret Configuration
1. In the left menu of the registered app, select **Certificates & secrets**.
2. Click **New client secret**.
3. Add a description and select an expiration period. Click **Add**.
4. Copy the **Value** of the client secret immediately. You will need it for the `CLIENT_SECRET` environment variable.

### 3. API Permissions
1. In the left menu of the registered app, select **API permissions**.
2. Click **Add a permission** and choose **Microsoft Graph**.
3. Select **Application permissions** (do not select Delegated permissions).
4. Add the following permissions:
   *   `OnlineMeetingTranscript.Read.All` (Required to list, read, and subscribe to transcripts)
   *   `OnlineMeetings.Read.All` (Required to get meeting details and resolve organizer details)
5. Click **Add permissions**.
6. Select **Grant admin consent for <your-tenant-name>** at the bottom of the API permissions screen to approve the permissions.

---

## 4. Microsoft Teams Application Access Policy

By default, even with application permissions granted in Entra ID, daemon applications cannot read online meetings or transcripts unless they are explicitly authorized by a Teams Application Access Policy.

An administrator must configure this policy using the **Microsoft Teams PowerShell Module**.

### Execution Steps
Open a PowerShell session and execute the following commands:

```powershell
# 1. Install the Microsoft Teams PowerShell module (if not already installed)
Install-Module -Name MicrosoftTeams -Force -AllowClobber

# 2. Connect to Microsoft Teams as a tenant administrator
Connect-MicrosoftTeams

# 3. Create the Application Access Policy linking your App's Client ID (App ID)
New-CsApplicationAccessPolicy -Identity "MeridianTeamsIntelligencePolicy" `
                              -AppIds "YOUR_ENTRA_APP_CLIENT_ID" `
                              -Description "Authorize Meridian Webhook daemon to fetch meeting details and transcripts"

# 4. Grant the policy
# Option A: Grant globally (recommended so it works for all meetings in the tenant dynamically)
Grant-CsApplicationAccessPolicy -PolicyName "MeridianTeamsIntelligencePolicy" -Global

# Option B: Grant only to a specific organizer user (for pilot groups or limited scope testing)
Grant-CsApplicationAccessPolicy -PolicyName "MeridianTeamsIntelligencePolicy" -Identity "organizer-user-id-or-upn@yourdomain.com"
```

### Verification
To verify the policy was created and assigned correctly, run:
```powershell
Get-CsApplicationAccessPolicy -Identity "MeridianTeamsIntelligencePolicy"
```
To verify user assignment:
```powershell
Get-CsOnlineUser -Identity "organizer-user-id-or-upn@yourdomain.com" | Select-Object ApplicationAccessPolicy
```
