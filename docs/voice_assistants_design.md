# Epic: Voice Assistant Integrations (Alexa, Google Assistant, Siri)

## Overview
Integrating ListMate with voice assistants allows users to seamlessly add items to their grocery lists hands-free (e.g., "Alexa, ask ListMate to add milk"). 

## Is it as simple as it sounds?
**No.** While the concept is simple, the execution is complex. The hardest part is not parsing the voice commands, but rather **Authentication (Account Linking)** and **State Management** (figuring out *which* household list to add the item to).

## Major Gotchas & Challenges

1. **OAuth Account Linking**
   - Both Alexa and Google Assistant require OAuth 2.0 Account Linking. When a user enables the ListMate skill, they must log in to ListMate via an OAuth flow. 
   - We will need to build an OAuth 2.0 provider on our backend (authorization endpoint, token endpoint) to issue tokens to Amazon/Google. 

2. **Native iOS Tie-in for Siri**
   - Siri does not call a cloud webhook directly like Alexa does. Siri integrates via **App Intents** (Siri Shortcuts) running on the user's iOS device.
   - This means Siri integration must be built natively in the iOS App (Swift/Kotlin/React Native) rather than entirely on our web backend.

3. **Multiple Households**
   - A single user might belong to multiple households. If they say "Add milk," which list does it go to?
   - **Solution**: We need a "Default Household" setting for voice commands, or prompt the user for clarification (which adds friction).

4. **Latency Requirements**
   - Voice assistants enforce strict timeout limits (typically 3 to 8 seconds). If our database or server takes too long to respond, the assistant will fail with "ListMate is not responding."

5. **Certification & Review**
   - Publishing an Alexa Skill or Google Action requires passing a manual review process, providing privacy policies, and ensuring all edge cases (like asking for help or cancelling) are handled gracefully.

## High-Level Design by Platform

### 1. Amazon Alexa
- **Component**: Custom Alexa Skill
- **Interaction Model**: Invocation Name: "ListMate". Intent: `AddItemIntent` with a slot `{ItemName}`.
- **Backend**: We expose a new webhook (e.g., `/api/voice/alexa/webhook`).
- **Auth**: User links account. Alexa sends an Access Token in every webhook payload.
- **Flow**: Alexa -> Webhook -> Validate Token -> Find User -> Add Item -> Return SSML Response.

### 2. Google Assistant (Actions on Google)
- *Note: Google recently deprecated Conversational Actions in favor of App Actions (Android).*
- **Component**: Android App Actions (BII - Built-in Intents).
- **Interaction**: "Hey Google, add milk to ListMate."
- **Flow**: Google Assistant triggers an intent directly to our installed Android app. The Android app receives the intent, adds the item locally, and syncs it to the backend via our existing API.

### 3. Apple Siri (App Intents)
- **Component**: App Intents framework (iOS).
- **Interaction**: "Hey Siri, add milk to ListMate."
- **Flow**: The iOS app defines an intent (e.g., `AddGroceryItemIntent`). Siri executes this intent on the device in the background. The app securely communicates with our backend API using the user's existing app session.

