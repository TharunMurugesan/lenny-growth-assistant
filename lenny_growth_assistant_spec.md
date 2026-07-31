# The Lenny Growth Assistant - Master Project Specification

## 1. Product Requirements Document (PRD)
**Project Name:** The Lenny Growth Assistant
**Objective:** Build a full-stack, AI-powered conversational web application that ingests Lenny's Podcast transcripts, answers complex product management/growth questions, generates Ship30for30 style content, and renders code/markdown artifacts natively in a side-by-side UI.

### Core Features & Requirements
1.  **Conversational Interface:** ChatGPT-like UI with session management (New Chat, Chat History).
2.  **LLM Agnosticism (The Toggle):** Users must be able to switch between Cloud LLMs (Anthropic Claude/OpenAI) and Local LLMs (Ollama) seamlessly.
3.  **Knowledge Base (RAG):** Ingestion of transcripts from `https://github.com/ChatPRD/lennys-podcast-transcripts`.
4.  **Agentic Skills (Routing):**
    *   *Skill A (Q&A):* Strict answering based *only* on Lenny's insights using RAG.
    *   *Skill B (Ship30for30 Content):* Synthesize answers into a 1250-word essay with a strong hook, bullet points, bold text, and a clear takeaway.
5.  **Artifact Viewer:** When the AI outputs HTML, CSS, or Markdown, the frontend must render it side-by-side with the chat (similar to Claude Artifacts). Do not redirect to external viewers.

---

## 2. System Architecture & Tech Stack
*   **Frontend:** React (tailored for seamless integration with FastAPI).
*   **Backend:** FastAPI (Python).
*   **Database:** PostgreSQL (hosted on Supabase or Railway).
*   **Agent Framework:** LangChain or LlamaIndex (for RAG and Agent routing), utilizing Anthropic SDK and local Ollama integrations.
*   **Embeddings & Vector Store:** pgvector (integrated with Postgres) or a local vector store like ChromaDB/FAISS if preferred for local setup.

---

## 3. Database Schema (Postgres)
We require a relational model to store users, sessions, and messages.

*   **Users Table:** `id` (UUID), `created_at`
*   **Sessions Table:** `id` (UUID), `user_id` (FK), `title` (String), `created_at` (Timestamp), `updated_at` (Timestamp).
*   **Messages Table:** `id` (UUID), `session_id` (FK), `role` (Enum: user/assistant), `content` (Text), `artifact_type` (Enum: none/html/markdown), `artifact_content` (Text), `created_at` (Timestamp).

---

## 4. API Endpoints (FastAPI)
*   `POST /api/sessions` - Create a new chat session.
*   `GET /api/sessions` - Retrieve all sessions for the history sidebar.
*   `GET /api/sessions/{session_id}/messages` - Fetch chat history for a session.
*   `POST /api/chat` - Main endpoint for sending messages. 
    *   *Payload:* `{ session_id, message, llm_provider (cloud/local) }`
    *   *Response:* Streaming response (Server-Sent Events) yielding text and artifact data.

---

## 5. Agentic Routing Logic
The backend must implement an Intent Classifier (Router) before processing the final prompt:
1.  **Analyze User Input:** Determine if the user is asking a standard Q&A question, requesting a Ship30for30 essay, or asking for UI/Code generation.
2.  **Route to Tool/Skill:**
    *   *If Q&A:* Execute Vector Search -> Retrieve Context -> Synthesize Answer (Strictly grounded).
    *   *If Ship30for30:* Execute Vector Search -> Retrieve Context -> Apply formatting constraints (1250 words, hooks, bolding).
    *   *If Code/Artifact:* Generate response wrapping code in specific XML or JSON tags (e.g., `<artifact type="html">...</artifact>`) so the frontend can parse and render it in the Artifact Viewer.

---

## 6. UI/UX Design (design.md directives)
*   **Layout:** Two-pane design. Left pane is the chat interface (collapsible history sidebar). Right pane is the Artifact Viewer (hidden until an artifact is generated).
*   **Styling:** Modern, clean, minimalistic. Use a unified color palette (referencing `Impeccable.style` principles). Dark mode support is highly recommended.
*   **Artifact Viewer:** Must safely render HTML/CSS (using an iframe or sanitized injection) and parse Markdown into rendered components.

---

## 7. Submission Checklist & Deliverables
The final repository must include:
*   [ ] `README.md`: Architecture overview, deployment steps, env vars, dependency installation.
*   [ ] `design.md`: UI/UX design structure and thoughts.
*   [ ] `PRD.md`: The formalized product requirement document based on this spec.
*   [ ] `architecture.md`: DB schema, API endpoints, agent routing logic.
*   [ ] `agent_transcripts/`: Folder containing logs of prompts used with Claude/Coding Agents, including failures and corrections.
*   [ ] Full working codebase (FastAPI + React).
*   [ ] (Manual Step): Record a 2-3 minute YouTube demo video.
