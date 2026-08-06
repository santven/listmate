# User Story: In-App Microphone / Speech-to-Text Integration

## Title
As a ListMate user, I want to tap a microphone icon within the app and speak my items (e.g., "Add milk and eggs") so that they are automatically parsed and added to my grocery list without typing.

## Problem Statement
While typing items into the text box is straightforward, it can be cumbersome when users are busy in the kitchen (e.g., hands are wet/dirty) or when trying to quickly dictate a long list of items before forgetting them. A previous attempt utilizing system-level Google Assistant ("Hey Google, add...") encountered reliability issues and conflicts with Google Keep intents. An in-app solution provides complete control over the intent, feedback, and execution.

## Acceptance Criteria
1. **UI Presence**: A prominent microphone icon is placed next to the item input field (or floating action button).
2. **Permissions**: Tapping the icon for the first time prompts the user for audio/microphone permissions cleanly.
3. **Voice Recognition (Active State)**:
   - When tapped, the UI visually indicates it is listening (e.g., pulsing red microphone icon, overlay with "Listening...").
4. **Processing**: 
   - Uses device-native Speech Recognition (Web Speech API for web, or Capacitor Voice Recognition plugin for native).
   - Once speech stops, the transcribed text is sent to the existing item parser.
5. **Item Addition**: 
   - The parser intelligently splits multiple items if spoken naturally (e.g., "Add milk, eggs, and bread" -> three items).
   - Items are automatically added to the current active household/store.
6. **Feedback**: 
   - A brief success toast ("Added 3 items via Voice") confirms the action.
   - If speech isn't recognized, a soft error toast ("Could not hear you, try again") is displayed.

## Technical Design & Architecture
- **Plugin Selection**: Investigate `@capacitor-community/speech-recognition` for robust native iOS/Android support. Fall back to standard Web Speech API (`window.SpeechRecognition`) for the web application.
- **State Management**: Introduce `isListening` state to handle the UI toggle (pulsing animation).
- **Error Handling**: Graceful degradation if permissions are denied (hide the microphone icon or show a tooltip explaining how to enable it in OS settings).
- **LLM / Parsing Layer**: Feed the transcript directly into the existing `categorize.py` logic (or a lightweight client-side equivalent) to split sentences into actionable items and categorize them appropriately.

## Risks & Mitigations
- **Risk**: Capacitor speech recognition plugin might have spotty maintenance.
- **Mitigation**: Sandbox the integration. Implement a purely web-based prototype using `webkitSpeechRecognition` first to gauge accuracy.
- **Risk**: Ambient noise in grocery stores or kitchens causing bad transcriptions.
- **Mitigation**: Allow users to review the dictated text in the input box before final submission, rather than auto-submitting instantly (configurable setting: "Auto-add voice items").

## Next Steps (Backlog)
- [ ] Evaluate and install `@capacitor-community/speech-recognition`.
- [ ] Design the UI states (Default, Listening, Processing).
- [ ] Build the transcription -> item extraction pipeline.
- [ ] Beta test with a small group of active users.
