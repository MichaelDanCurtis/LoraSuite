import { Bot, ChevronDown, ChevronUp, Send, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import type { WizardTarget } from "./WorkflowWizard";

export type GuidedCopilotStage = "create" | "sources" | "prepare" | "verify" | "build" | "evaluate";

interface GuidedCopilotContext {
  stage: GuidedCopilotStage;
  target: WizardTarget;
  relevantMediaCount: number;
  identifyItemCount: number;
  hasProject: boolean;
  evaluationReady: boolean;
}

interface GuidedCopilotAction {
  label: string;
  onClick(): void;
}

interface GuidedCopilotProps extends GuidedCopilotContext {
  action?: GuidedCopilotAction | null;
}

interface CopilotMessage {
  id: number;
  role: "assistant" | "user";
  text: string;
}

export function GuidedCopilot(props: GuidedCopilotProps) {
  const guidance = useMemo(() => stageGuidance(props), [
    props.stage,
    props.target,
    props.relevantMediaCount,
    props.identifyItemCount,
    props.hasProject,
    props.evaluationReady,
  ]);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<CopilotMessage[]>(() => [assistantMessage(guidance)]);
  const messageId = useRef(1);
  const lastGuidance = useRef(guidance);
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (guidance === lastGuidance.current) return;
    lastGuidance.current = guidance;
    messageId.current += 1;
    setMessages((current) => [
      ...current,
      assistantMessage(guidance, messageId.current),
    ].slice(-12));
  }, [guidance]);

  useEffect(() => {
    if (!open || !transcriptRef.current) return;
    transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [messages, open]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question) return;
    const userId = messageId.current + 1;
    const assistantId = messageId.current + 2;
    messageId.current = assistantId;
    setMessages((current) => [
      ...current,
      userMessage(question, userId),
      assistantMessage(answerQuestion(question, props), assistantId),
    ].slice(-12));
    setDraft("");
  }

  return (
    <aside className={`guided-copilot ${open ? "open" : "collapsed"}`} aria-label="Ask AI">
      <button
        className="guided-copilot-toggle"
        type="button"
        aria-label={`${open ? "Collapse" : "Open"} Ask AI`}
        aria-expanded={open}
        title={open ? "Minimize Ask AI" : "Open Ask AI"}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? (
          <span className="guided-copilot-header-icon"><Bot size={17} aria-hidden="true" /></span>
        ) : (
          <Sparkles className="guided-copilot-launcher-icon" size={17} aria-hidden="true" />
        )}
        <strong>Ask AI</strong>
        <small>{stageLabel(props.stage)}</small>
        {open ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronUp size={15} aria-hidden="true" />}
      </button>
      {open ? (
        <div className="guided-copilot-body">
          <div className="guided-copilot-transcript" ref={transcriptRef} aria-live="polite">
            {messages.map((message) => (
              <p className={message.role} key={message.id}>
                {message.role === "assistant" ? <Sparkles size={13} aria-hidden="true" /> : null}
                <span>{message.text}</span>
              </p>
            ))}
          </div>
          <div className="guided-copilot-controls">
            {props.action ? <button className="guided-copilot-action" type="button" onClick={props.action.onClick}>{props.action.label}</button> : null}
            <form onSubmit={submit}>
              <input
                aria-label="Ask AI a question"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask what to do next, what is blocked, or how anchoring works"
              />
              <button type="submit" title="Send" disabled={!draft.trim()}><Send size={15} aria-hidden="true" /></button>
            </form>
          </div>
        </div>
      ) : null}
    </aside>
  );
}

function assistantMessage(text: string, id = 1): CopilotMessage {
  return { id, role: "assistant", text };
}

function userMessage(text: string, id: number): CopilotMessage {
  return { id, role: "user", text };
}

function stageGuidance(context: GuidedCopilotContext): string {
  const target = targetLabel(context.target);
  if (context.stage === "create") {
    const article = context.target === "image" ? "an" : "a";
    return `Choose the result you want. I will adapt every later decision to ${article} ${target}.`;
  }
  if (context.stage === "sources") {
    return context.relevantMediaCount > 0
      ? `You have ${context.relevantMediaCount} usable source item${context.relevantMediaCount === 1 ? "" : "s"}. Add another source or let me prepare them.`
      : "Start with any source. Retrieval only gathers previews; nothing enters the dataset until you approve it.";
  }
  if (context.stage === "prepare") {
    return `I can inspect all ${context.relevantMediaCount} source item${context.relevantMediaCount === 1 ? "" : "s"} in one pass, stage the strongest evidence, and leave uncertain decisions for you.`;
  }
  if (context.stage === "verify") {
    return context.identifyItemCount > 0
      ? `I am checking identity across ${context.identifyItemCount} prepared item${context.identifyItemCount === 1 ? "" : "s"}. Confirm a detected face with “Anchor this person”; I will compare the rest against that identity.`
      : "Verify needs prepared evidence. Go back to Prepare and keep at least one clear reference item.";
  }
  if (context.stage === "build") {
    return context.hasProject
      ? "The identity project is connected. I will apply the selected model recipe, package the approved dataset, and show the exact training blocker if one remains."
      : "Build needs a verified identity project. Return to Verify and confirm the required identity evidence first.";
  }
  return context.evaluationReady
    ? "A trained result is ready. I will compare identity, quality, and failure cases and turn any weakness into a concrete next revision."
    : "Evaluation begins when a trained result returns from the selected provider. The exported package remains available while you wait.";
}

function answerQuestion(question: string, context: GuidedCopilotContext): string {
  const normalized = question.toLowerCase();
  if (/anchor|which person|right person|face/.test(normalized)) {
    return "In Verify, open a reference or uncertain photo. If several faces were detected, choose the correct face, then click “Anchor this person.” That saves the face as trusted identity evidence and reruns consensus across every candidate.";
  }
  if (/block|stuck|can.?t|cannot|disabled|grey|gray/.test(normalized)) {
    return blockerExplanation(context);
  }
  if (/audio|voice|speaker/.test(normalized)) {
    return "Voice uses its own trusted anchors. Pick a clean clip spoken by the subject, mark it as the reference voice, then compare the remaining samples. Music-heavy or uncertain clips stay in review instead of being silently accepted.";
  }
  if (/video|motion|frame/.test(normalized)) {
    return "Video is preserved as motion evidence and can also produce image frames. Prepare chooses stable visual ranges; Verify confirms subject continuity before the clip enters the video dataset.";
  }
  if (/train|build|model|flux|qwen|krea|runcomfy|runpod/.test(normalized)) {
    return "Build chooses the target model recipe, freezes the approved evidence, writes captions and metadata, and packages it for RunComfy or RunPod. Training stays external; LoraSuite tracks the submitted job and evaluates the returned model.";
  }
  if (/source|instagram|twitter|tiktok|local|import|retrieve/.test(normalized)) {
    return "Sources are additive. Retrieve previews first, let AI stage likely keep/review/reject decisions, adjust anything you disagree with, then confirm only the media you want in the vault.";
  }
  if (/next|what.*do|help|guide|continue|proceed/.test(normalized)) return stageGuidance(context);
  return `${stageGuidance(context)} Ask me about the current blocker, identity anchors, source selection, video, voice, or training.`;
}

function blockerExplanation(context: GuidedCopilotContext): string {
  if (context.stage === "sources" && context.relevantMediaCount === 0) return "Nothing is prepared yet because no source media has been approved. Open a source, retrieve a batch, and confirm at least one item.";
  if (context.stage === "prepare" && context.relevantMediaCount === 0) return "Prepare has no source evidence. Return to Sources and approve media first.";
  if (context.stage === "verify" && context.identifyItemCount === 0) return "Verify has no prepared evidence. Return to Prepare and accept at least one item that clearly shows or contains the subject.";
  if (context.stage === "build" && !context.hasProject) return "There is no verified identity project yet. Return to Verify, anchor the person or speaker, and complete the required checks.";
  if (context.stage === "evaluate" && !context.evaluationReady) return "No trained artifact has returned yet. Finish a provider training run in Build & Train, then evaluation will unlock automatically.";
  return "The current screen shows the remaining requirement beside its disabled action. I will keep the requirement current as media, identity evidence, and provider outputs change.";
}

function stageLabel(stage: GuidedCopilotStage): string {
  return ({
    create: "Create",
    sources: "Sources",
    prepare: "Prepare",
    verify: "Verify",
    build: "Build & Train",
    evaluate: "Evaluate",
  } as Record<GuidedCopilotStage, string>)[stage];
}

function targetLabel(target: WizardTarget): string {
  return ({ image: "image LoRA", video: "video LoRA", voice: "voice dataset", id_lora: "living identity" } as Record<WizardTarget, string>)[target];
}
