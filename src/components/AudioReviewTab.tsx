import { ArrowLeft, AudioLines, Check, Clock3, Download, FlaskConical, Save, Sparkles, UserRoundCheck, Waves, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { AudioCleaningRecipe, AudioCleaningResult, AudioSeparationRuntimeStatus, CurationAnalysisEvidence, MediaItem } from "../lib/types";

interface AudioReviewTabProps {
  item: MediaItem;
  artworkItem?: MediaItem;
  evidence?: CurationAnalysisEvidence;
  selected: boolean;
  analyzing: boolean;
  assetUrl(path: string): string;
  onAnalyze(): void;
  onBack(): void;
  onKeep(): void;
  onReject(): void;
  loadCleaningRecipe(): Promise<AudioCleaningRecipe>;
  previewCleaning(recipe: AudioCleaningRecipe): Promise<AudioCleaningResult>;
  renderCleaning(recipe: AudioCleaningRecipe): Promise<AudioCleaningResult>;
  loadSeparationStatus(): Promise<AudioSeparationRuntimeStatus>;
  installSeparationModel(): Promise<AudioSeparationRuntimeStatus>;
  onDerivativeRendered(item: MediaItem): void;
}

export function AudioReviewTab({
  item,
  artworkItem,
  evidence,
  selected,
  analyzing,
  assetUrl,
  onAnalyze,
  onBack,
  onKeep,
  onReject,
  loadCleaningRecipe,
  previewCleaning,
  renderCleaning,
  loadSeparationStatus,
  installSeparationModel,
  onDerivativeRendered,
}: AudioReviewTabProps) {
  const [measuredDuration, setMeasuredDuration] = useState<number | null>(null);
  const [recipe, setRecipe] = useState<AudioCleaningRecipe>(() => defaultRecipe(item.id));
  const [cleaningResult, setCleaningResult] = useState<AudioCleaningResult | null>(null);
  const [audition, setAudition] = useState<"original" | "processed">("original");
  const [cleaningBusy, setCleaningBusy] = useState<"preview" | "render" | null>(null);
  const [separationBusy, setSeparationBusy] = useState(false);
  const [separationStatus, setSeparationStatus] = useState<AudioSeparationRuntimeStatus | null>(null);
  const [cleaningStatus, setCleaningStatus] = useState("Loading saved recipe...");
  const source = item.raw_path ? assetUrl(item.raw_path) : undefined;
  const artwork = artworkItem?.raw_path ? assetUrl(artworkItem.raw_path) : undefined;
  const originalAudio = item.metadata_json?.audio_original;
  const evidenceIdentifiesReusedAudio = evidence?.reasons.some((reason) =>
    reason.toLowerCase().includes("reused or musical"),
  ) ?? false;
  const sourceLabel = originalAudio === true
    ? "Original source audio"
    : originalAudio === false || evidenceIdentifiesReusedAudio
      ? "Reused or musical source"
      : "Source ownership unknown";
  const activeRatio = evidence?.active_audio_ratio ?? null;
  const silenceRatio = activeRatio === null ? null : Math.max(0, 1 - activeRatio);
  const clippingRatio = evidence?.clipping_ratio ?? null;
  const processedSource = cleaningResult ? assetUrl(cleaningResult.preview_path) : undefined;
  const auditionSource = audition === "processed" && processedSource ? processedSource : source;

  useEffect(() => {
    let ignore = false;
    void loadCleaningRecipe()
      .then((savedRecipe) => {
        if (!ignore) {
          setRecipe(savedRecipe);
          setCleaningStatus("Recipe ready. Preview to audition changes.");
        }
      })
      .catch((error) => {
        if (!ignore) setCleaningStatus(`Recipe error: ${errorMessage(error)}`);
      });
    return () => {
      ignore = true;
    };
  }, [item.id]);

  useEffect(() => {
    let ignore = false;
    void loadSeparationStatus()
      .then((status) => {
        if (!ignore) setSeparationStatus(status);
      })
      .catch((error) => {
        if (!ignore) {
          setCleaningStatus(`Isolation status error: ${errorMessage(error)}`);
        }
      });
    return () => {
      ignore = true;
    };
  }, [item.id]);

  function updateRecipe(update: Partial<AudioCleaningRecipe>) {
    setRecipe((current) => ({ ...current, ...update }));
    setCleaningResult(null);
    setAudition("original");
    setCleaningStatus("Settings changed. Generate a new preview.");
  }

  async function generatePreview() {
    setCleaningBusy("preview");
    setCleaningStatus("Rendering non-destructive preview...");
    try {
      const result = await previewCleaning(recipe);
      setRecipe(result.recipe);
      setCleaningResult(result);
      setAudition("processed");
      setCleaningStatus(
        result.warnings[0]
          ?? (result.isolation_applied
            ? "Isolated vocal preview ready. Compare it with the original."
            : "Preview ready. Compare it with the original."),
      );
    } catch (error) {
      setCleaningStatus(`Preview error: ${errorMessage(error)}`);
    } finally {
      setCleaningBusy(null);
    }
  }

  async function renderDerivative() {
    setCleaningBusy("render");
    setCleaningStatus("Rendering approved training derivative...");
    try {
      const result = await renderCleaning(recipe);
      setRecipe(result.recipe);
      setCleaningResult(result);
      if (result.rendered_media_item) onDerivativeRendered(result.rendered_media_item);
      setAudition("processed");
      setCleaningStatus(
        result.warnings[0]
          ?? (result.isolation_applied
            ? "Isolated vocal derivative added to the vault."
            : "Clean audio derivative added to the vault."),
      );
    } catch (error) {
      setCleaningStatus(`Render error: ${errorMessage(error)}`);
    } finally {
      setCleaningBusy(null);
    }
  }

  async function downloadSeparationModel() {
    setSeparationBusy(true);
    setCleaningStatus("Downloading and verifying the vocal-isolation model...");
    try {
      const status = await installSeparationModel();
      setSeparationStatus(status);
      setCleaningStatus(status.message);
    } catch (error) {
      setCleaningStatus(`Isolation setup error: ${errorMessage(error)}`);
    } finally {
      setSeparationBusy(false);
    }
  }

  return (
    <section className="audio-review-workspace" aria-label={`Audio review: ${displayName(item)}`}>
      <header className="audio-review-header">
        <div>
          <button type="button" onClick={onBack}>
            <ArrowLeft size={14} aria-hidden="true" /> Audio
          </button>
          <span>
            <strong>Audio Review</strong>
            <small>{displayName(item)}</small>
          </span>
        </div>
        <div className="audio-review-actions">
          <button type="button" onClick={onAnalyze} disabled={analyzing}>
            <Sparkles size={14} aria-hidden="true" /> {analyzing ? "Analyzing" : "Analyze Track"}
          </button>
          <button className={selected ? "primary-action selected" : "primary-action"} type="button" onClick={onKeep}>
            <Check size={14} aria-hidden="true" /> {selected ? "Selected" : "Keep for Identify"}
          </button>
          <button className="audio-review-reject" type="button" onClick={onReject}>
            <X size={14} aria-hidden="true" /> Reject
          </button>
        </div>
      </header>

      <div className="audio-review-layout">
        <section className="audio-review-stage">
          <div className={artwork ? "audio-review-artwork has-artwork" : "audio-review-artwork"}>
            {artwork ? <img src={artwork} alt="" /> : <AudioLines size={54} aria-hidden="true" />}
            <span aria-hidden="true"><AudioLines size={28} /></span>
          </div>
          {auditionSource ? (
            <audio
              key={auditionSource}
              src={auditionSource}
              controls
              preload="metadata"
              onLoadedMetadata={(event) => {
                if (Number.isFinite(event.currentTarget.duration)) {
                  setMeasuredDuration(event.currentTarget.duration);
                }
              }}
            />
          ) : (
            <p>Audio file is unavailable.</p>
          )}
          <div className="audio-ab-controls" role="group" aria-label="Audition source">
            <button className={audition === "original" ? "active" : ""} type="button" onClick={() => setAudition("original")}>A Original</button>
            <button className={audition === "processed" ? "active" : ""} type="button" disabled={!processedSource} onClick={() => setAudition("processed")}>B Processed</button>
          </div>

          <section className="audio-cleaning-console" aria-label="Audio cleaning controls">
            <header>
              <div><FlaskConical size={15} aria-hidden="true" /><strong>Cleaning Recipe</strong></div>
              <div>
                <button type="button" onClick={() => void generatePreview()} disabled={cleaningBusy !== null}>
                  <Sparkles size={13} aria-hidden="true" /> {cleaningBusy === "preview" ? "Rendering" : "Preview"}
                </button>
                <button className="primary-action" type="button" onClick={() => void renderDerivative()} disabled={cleaningBusy !== null}>
                  <Save size={13} aria-hidden="true" /> {cleaningBusy === "render" ? "Rendering" : "Render Derivative"}
                </button>
              </div>
            </header>
            <div className="audio-cleaning-grid">
              <RecipeSlider label="Low cut" value={recipe.high_pass_hz} min={20} max={500} step={10} suffix="Hz" onChange={(value) => updateRecipe({ high_pass_hz: value })} />
              <RecipeSlider label="High cut" value={recipe.low_pass_hz} min={3000} max={22000} step={500} suffix="Hz" onChange={(value) => updateRecipe({ low_pass_hz: value })} />
              <RecipeSlider label="Noise floor" value={recipe.noise_floor_db} min={-80} max={-20} step={1} suffix="dB" onChange={(value) => updateRecipe({ noise_floor_db: value })} />
              <RecipeSlider label="Reduction" value={recipe.noise_reduction_db} min={0} max={30} step={1} suffix="dB" onChange={(value) => updateRecipe({ noise_reduction_db: value })} />
              <RecipeSlider label="Gate" value={recipe.gate_threshold_db} min={-80} max={-20} step={1} suffix="dB" onChange={(value) => updateRecipe({ gate_threshold_db: value })} />
              <RecipeSlider label="Presence" value={recipe.presence_gain_db} min={-12} max={12} step={0.5} suffix="dB" onChange={(value) => updateRecipe({ presence_gain_db: value })} />
            </div>
            <div className="audio-cleaning-toggles">
              <label><input type="checkbox" checked={recipe.normalize} onChange={(event) => updateRecipe({ normalize: event.target.checked })} /> Normalize loudness</label>
              <label title={separationStatus?.message ?? "Checking vocal-isolation runtime"}>
                <input
                  type="checkbox"
                  checked={recipe.isolate_voice}
                  disabled={!separationStatus?.ready}
                  onChange={(event) => updateRecipe({ isolate_voice: event.target.checked })}
                /> Isolate voice
              </label>
              {separationStatus && !separationStatus.model_installed && separationStatus.runtime_installed ? (
                <button type="button" onClick={() => void downloadSeparationModel()} disabled={separationBusy}>
                  <Download size={13} aria-hidden="true" />
                  {separationBusy ? "Installing" : "Install vocal model"}
                </button>
              ) : null}
              <small className={separationStatus?.ready ? "audio-separation-ready" : "audio-separation-missing"}>
                {separationStatus?.message ?? "Checking vocal isolation..."}
              </small>
              <span>{cleaningStatus}</span>
            </div>
          </section>
          <p>Use the mouse wheel over audio cards for fast scrubbing.</p>
        </section>

        <aside className="audio-review-inspector">
          <section>
            <h3>Source</h3>
            <dl className="audio-review-facts">
              <div><dt><Clock3 size={13} aria-hidden="true" /> Duration</dt><dd>{formatDuration(item.duration ?? measuredDuration)}</dd></div>
              <div><dt><UserRoundCheck size={13} aria-hidden="true" /> Ownership</dt><dd>{sourceLabel}</dd></div>
              <div>
                <dt><Waves size={13} aria-hidden="true" /> Speech</dt>
                <dd>{evidence?.word_count != null ? `${evidence.word_count} words detected` : "Requires verification"}</dd>
              </div>
              <div>
                <dt><UserRoundCheck size={13} aria-hidden="true" /> Speakers</dt>
                <dd>{evidence?.speaker_count != null ? evidence.speaker_count : "Unverified"}</dd>
              </div>
            </dl>
          </section>

          <section>
            <div className="audio-review-section-title">
              <h3>Signal Analysis</h3>
              {evidence ? <span className={`audio-review-recommendation ${evidence.recommendation}`}>{evidence.recommendation}</span> : null}
            </div>
            {evidence ? (
              <div className="audio-signal-metrics">
                <SignalMetric label="Active signal" value={activeRatio} />
                <SignalMetric label="Detected speech" value={evidence.speech_duration_ratio ?? null} />
                <SignalMetric label="Silence" value={silenceRatio} />
                <SignalMetric label="Clipping" value={clippingRatio} danger />
              </div>
            ) : (
              <p className="audio-review-empty">Run Analyze Track to measure activity, silence, and clipping.</p>
            )}
          </section>

          <section>
            <h3>Transcript</h3>
            {evidence?.transcript ? (
              <blockquote className="audio-review-transcript">{evidence.transcript}</blockquote>
            ) : (
              <p className="audio-review-empty">No transcript is available for this track.</p>
            )}
            {evidence?.language ? (
              <small>
                {evidence.language.toUpperCase()}
                {evidence.transcript_confidence != null
                  ? ` · ${Math.round(evidence.transcript_confidence * 100)}% transcript confidence`
                  : ""}
              </small>
            ) : null}
          </section>

          <section>
            <h3>Decision Evidence</h3>
            {evidence ? (
              <>
                <p className="audio-review-confidence">{Math.round(evidence.confidence * 100)}% recommendation confidence</p>
                <ul>
                  {evidence.reasons.map((reason) => <li key={reason}>{reason}</li>)}
                  {evidence.warnings.map((warning) => <li className="warning" key={warning}>{warning}</li>)}
                </ul>
                <small>{evidence.analyzer}</small>
              </>
            ) : (
              <p className="audio-review-empty">No local analysis has been run for this track.</p>
            )}
          </section>

          <section className="audio-review-limit">
            <strong>Current limitation</strong>
            <p>Transcription and diarization indicate speech and speaker count, but the intended speaker still requires a trusted reference voice or human confirmation.</p>
          </section>
        </aside>
      </div>
    </section>
  );
}

function RecipeSlider({ label, value, min, max, step, suffix, onChange }: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  onChange(value: number): void;
}) {
  return (
    <label className="audio-recipe-slider">
      <span><strong>{label}</strong><output>{value}{suffix}</output></span>
      <input aria-label={label} type="range" min={min} max={max} step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function defaultRecipe(mediaItemId: string): AudioCleaningRecipe {
  return {
    media_item_id: mediaItemId,
    high_pass_hz: 80,
    low_pass_hz: 14000,
    noise_floor_db: -55,
    noise_reduction_db: 6,
    gate_threshold_db: -55,
    presence_gain_db: 0,
    normalize: true,
    isolate_voice: false,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function SignalMetric({ label, value, danger = false }: { label: string; value: number | null; danger?: boolean }) {
  const percent = value === null ? 0 : Math.round(value * 100);
  return (
    <div className={danger ? "audio-signal-metric danger" : "audio-signal-metric"}>
      <span><strong>{label}</strong><small>{value === null ? "Unknown" : `${percent}%`}</small></span>
      <i aria-hidden="true"><b style={{ width: `${percent}%` }} /></i>
    </div>
  );
}

function formatDuration(duration?: number | null): string {
  if (duration == null || !Number.isFinite(duration)) return "Unknown";
  const minutes = Math.floor(duration / 60);
  const seconds = Math.round(duration % 60);
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function displayName(item: MediaItem): string {
  const normalized = (item.raw_path ?? item.id).replace(/\\/g, "/");
  return normalized.split("/").filter(Boolean).at(-1) ?? item.id;
}
