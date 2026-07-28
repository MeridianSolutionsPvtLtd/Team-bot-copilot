# Power Automate Integration Blueprint

This document details how the Power Automate cloud flow integrates with the Azure Functions webhook.

## 1. HTTP Trigger Endpoint
The Power Automate flow must begin with a **"When an HTTP request is received"** trigger.
*   **Request URL**: Configure this URL in the Azure Function's `POWER_AUTOMATE_URL` environment variable.
*   **Method**: `POST`

### 2. Request Body JSON Schema
Paste the following schema into the **"Request Body JSON Schema"** box of the trigger:

```json
{
  "type": "object",
  "properties": {
    "meetingId": {
      "type": "string"
    },
    "transcriptId": {
      "type": "string"
    },
    "meetingSubject": {
      "type": "string"
    },
    "organizerId": {
      "type": "string"
    },
    "transcriptLength": {
      "type": "integer"
    },
    "transcriptContent": {
      "type": "string"
    },
    "processedAt": {
      "type": "string"
    }
  },
  "required": [
    "meetingId",
    "transcriptId",
    "meetingSubject",
    "organizerId",
    "transcriptContent"
  ]
}
```

---

## 3. Downstream Cloud Flow Steps

Once the payload is received by Power Automate, configure the following actions in the flow:

### Step A: Groq AI Summarization
1. Add an **HTTP** action to invoke the Groq AI chat completion API.
2. **Method**: `POST`
3. **URI**: `https://api.groq.com/openai/v1/chat/completions`
4. **Headers**:
   *   `Authorization`: `Bearer YOUR_GROQ_API_KEY`
   *   `Content-Type`: `application/json`
5. **Body**:
   ```json
   {
     "model": "llama-3.1-70b-versatile",
     "messages": [
       {
         "role": "system",
         "content": "You are an executive assistant. Summarize the following Teams meeting transcript. Highlight decisions made, action items (with assignees), and key discussion points. Format output using clean HTML headers, lists, and tables."
       },
       {
         "role": "user",
         "content": "@{triggerBody()?['transcriptContent']}"
       }
     ]
   }
   ```

### Step B: SharePoint Storage
1. Add a **Create file** action in SharePoint.
2. Select your SharePoint site and target document library.
3. **File Name**: `Transcripts/@{triggerBody()?['meetingSubject']}_@{triggerBody()?['meetingId']}.vtt`
4. **File Content**: `@{triggerBody()?['transcriptContent']}`
5. Add a second **Create file** action to store the AI summary as a markdown or PDF file if desired.

### Step C: HTML Executive Email Generation
1. Add a **Send an email (V2)** Office 365 Outlook action.
2. **To**: Send to the organizer resolved from the webhook: `@{triggerBody()?['organizerId']}` (if organizerId is an email address/UPN, otherwise look up the user details using the Entra ID connector).
3. **Subject**: `[Meeting Intelligence] Summary: @{triggerBody()?['meetingSubject']}`
4. **Body (HTML)**:
   ```html
   <h2>Teams Meeting Intelligence Summary</h2>
   <p><strong>Meeting Subject:</strong> @{triggerBody()?['meetingSubject']}</p>
   <p><strong>Processed Date:</strong> @{triggerBody()?['processedAt']}</p>
   <hr/>
   <h3>Executive Summary & Action Items</h3>
   <!-- Inject output from Groq HTTP API call -->
   @{body('HTTP')?['choices'][0]['message']['content']}
   <hr/>
   <p style="font-size:11px;color:grey;">
     Automated by Meridian Teams Meeting Intelligence. Raw transcript archived in SharePoint.
   </p>
   ```
