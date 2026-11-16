"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ChatResponse, sendMessage } from "@/lib/api";

type Turn = {
  question: string;
  result?: ChatResponse;
  error?: string;
};

type ChatProps = {
  sessionId: string;
  connected: boolean;
  onBusyChange: (busy: boolean) => void;
};

function messageFromError(reason: unknown): string {
  return reason instanceof Error ? reason.message : "The request failed.";
}

export default function Chat({
  sessionId,
  connected,
  onBusyChange,
}: ChatProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [retrieving, setRetrieving] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, retrieving]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = question.trim();
    if (!prompt || !sessionId || !connected || busy) return;
    setQuestion("");
    setBusy(true);
    onBusyChange(true);
    setRetrieving(true);
    const index = turns.length;
    setTurns((current) => [...current, { question: prompt }]);
    try {
      const result = await sendMessage(sessionId, prompt);
      setTurns((current) =>
        current.map((turn, turnIndex) =>
          turnIndex === index ? { ...turn, result } : turn,
        ),
      );
    } catch (reason) {
      const message = messageFromError(reason);
      setTurns((current) =>
        current.map((turn, turnIndex) =>
          turnIndex === index ? { ...turn, error: message } : turn,
        ),
      );
    } finally {
      setRetrieving(false);
      setBusy(false);
      onBusyChange(false);
    }
  }

  return (
    <>
      <section className="panel chat-panel">
        <div className="chat-panel-heading">
          <div>
            <p className="section-kicker">Folium Agents</p>
            <h2>Ask about Clinical or Financials</h2>
          </div>
          <span className="read-only-badge">Read only</span>
        </div>
        <section
          className="conversation"
          aria-live="polite"
          aria-label="Conversation"
        >
          {turns.length === 0 && (
            <div className="empty-chat">
              <span className="empty-chat-icon" aria-hidden="true">
                ?
              </span>
              <h3>
                {connected ? "What would you like to know?" : "Chat unavailable"}
              </h3>
              <p className="muted">
                {connected
                  ? "Ask about authorized clinical records or claims. Answers use available evidence and disclose missing information."
                  : "Connect an authorized patient before starting a conversation."}
              </p>
            </div>
          )}
          {turns.map((turn, index) => (
            <article className="turn" key={`${index}-${turn.question}`}>
              <p className="user-message">{turn.question}</p>
              {turn.result && (
                <div className="assistant-message">
                  <p>{turn.result.answer}</p>
                  {turn.result.sources.length > 0 && (
                    <details>
                      <summary>Sources ({turn.result.sources.length})</summary>
                      <ul>
                        {turn.result.sources.map((source) => (
                          <li
                            key={`${source.sourceType}/${source.sourceId}`}
                          >
                            <strong>
                              {source.sourceType}/{source.sourceId}
                            </strong>
                            {" — "}
                            {source.title}
                            {source.status && ` · ${source.status}`}
                            {source.date && ` · ${source.date}`}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                  {turn.result.limitations?.map((limitation, itemIndex) => (
                    <p className="muted" key={`${itemIndex}-${limitation}`}>
                      Coverage: {limitation}
                    </p>
                  ))}
                  {turn.result.warnings.map((warning, itemIndex) => (
                    <p className="warning" key={`${itemIndex}-${warning}`}>
                      Retrieval warning: {warning.replace(/\.$/, "")}. This
                      response may be incomplete.
                    </p>
                  ))}
                </div>
              )}
              {turn.error && (
                <p role="alert" className="error">
                  {turn.error}
                </p>
              )}
            </article>
          ))}
          {retrieving && (
            <p className="muted" role="status">
              Retrieving authorized records...
            </p>
          )}
          <div ref={endRef} />
        </section>
        <form className="composer" onSubmit={submit}>
          <label className="sr-only" htmlFor="question">
            Ask a Clinical or Financials question
          </label>
          <textarea
            id="question"
            rows={2}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about clinical records or claims"
            disabled={!connected || busy}
          />
          <Button
            type="submit"
            disabled={!connected || busy || !question.trim()}
          >
            {busy ? "Sending..." : "Send"}
          </Button>
        </form>
      </section>
      <p className="clinical-disclaimer">
        Synthetic data only. Responses are not a substitute for clinical
        judgment and do not diagnose, recommend treatment, place orders, or
        change the medical record. Financial responses require human review; no
        payments or other financial actions are executed.
      </p>
    </>
  );
}
