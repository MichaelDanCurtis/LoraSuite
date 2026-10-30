import { describe, expect, it, vi } from "vitest";

import { createEngineClient } from "./api";

describe("createEngineClient", () => {
  it("previews ComfyUI handoffs and reads returned evaluation reports", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.previewModelArtifactComfyHandoff?.(
      "artifact/1",
      "/tmp/Comfy UI",
    );
    await client.listComfyEvaluationReports?.({
      artifactId: "artifact/1",
      projectId: "project 1",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://engine.test/model-artifacts/artifact%2F1/comfyui-handoff?comfy_root=%2Ftmp%2FComfy+UI",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://engine.test/comfyui/evaluation-reports?artifact_id=artifact%2F1&project_id=project+1",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
  });

  it("reads the unified cloud provider contract and normalized run history", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listCloudProviders?.();
    await client.listCloudRuns?.("project/1", "runpod");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/cloud-providers", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://engine.test/cloud-runs?project_id=project%2F1&provider=runpod",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
  });

  it("reads a project partner qualification report", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ format: "lorasuite.partner-qualification.v1", lanes: [] }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.getPartnerQualificationReport?.("project/1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/partner-qualification/project%2F1",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
  });

  it("registers and verifies immutable recovered dataset exports", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listRecoveredDatasetExports?.();
    await client.registerRecoveredDatasetExport?.("/Volumes/Example Drive/test");
    await client.verifyRecoveredDatasetExport?.("recovered/export 1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://engine.test/recovered-dataset-exports",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://engine.test/recovered-dataset-exports",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ export_path: "/Volumes/Example Drive/test" }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://engine.test/recovered-dataset-exports/recovered%2Fexport%201/verify",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
  });

  it("inspects state migrations and creates downloadable diagnostic bundles", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.inspectStateMigrations?.();
    await client.applyStateMigrations?.();
    await client.listDiagnosticBundles?.();
    await client.createDiagnosticBundle?.({
      comfy_root: "/tmp/Comfy UI",
      comfy_base_url: "http://127.0.0.1:8188",
      project_id: "project_1",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/state-migrations", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/state-migrations/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/diagnostic-bundles", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/diagnostic-bundles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        comfy_root: "/tmp/Comfy UI",
        comfy_base_url: "http://127.0.0.1:8188",
        project_id: "project_1",
      }),
    });
    expect(client.diagnosticBundleDownloadUrl?.("bundle/1")).toBe(
      "http://engine.test/diagnostic-bundles/bundle%2F1/download",
    );
  });

  it("requests a provider training estimate without sending credentials", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ available: true }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.estimateTraining?.({
      provider: "runpod",
      training_target_profile_id: "runcomfy_flux1_dev_character",
      gpu_type: "NVIDIA H100 80GB HBM3",
      pricing_tier: "flex",
    });

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/training-estimates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider: "runpod",
        training_target_profile_id: "runcomfy_flux1_dev_character",
        gpu_type: "NVIDIA H100 80GB HBM3",
        pricing_tier: "flex",
      }),
    });
  });

  it("posts local import paths to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        media_items: [{ id: "media_1", media_type: "image" }],
        errors: [],
      }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    const result = await client.importLocal(["/tmp/a.png"]);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/vault/import/local", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: ["/tmp/a.png"] }),
    });
    expect(result.media_items[0].id).toBe("media_1");
    expect(result.errors).toEqual([]);
  });

  it("queries a stable filtered vault media page", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        items: [],
        offset: 250,
        limit: 250,
        total: 500,
        has_more: false,
        next_offset: null,
        snapshot: "snapshot-1",
      }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listVaultMediaPage?.({
      offset: 250,
      limit: 250,
      mediaType: "video",
      status: "reviewed",
      search: "source bundle",
      includeIgnored: true,
      snapshot: "snapshot-1",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/vault/media-page?offset=250&limit=250&media_type=video&status=reviewed&search=source+bundle&include_ignored=true&snapshot=snapshot-1",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
  });

  it("rotates a vault image in place by media id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "media/portrait",
        media_type: "image",
        raw_path: "/vault/rotated.png",
      }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.rotateVaultImage("media/portrait", 90);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/vault/media/media%2Fportrait/rotate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ degrees: 90 }),
      },
    );
  });

  it("persists cross-media curation handoffs and review decisions", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], updated_at: "2026-07-10T00:00:00Z" }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listCurationBundles();
    await client.getCurationHandoff("project 1", "video");
    await client.addCurationHandoff(["media_video"], "project 1", "video");
    await client.updateCurationReview(
      "media/video",
      "accepted",
      "project 1",
      "video",
    );
    await client.rejectCurationMedia(["media_audio"]);
    await client.restoreCurationAudio(["media_audio"]);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/curation/bundles", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/curation/handoff?project_id=project+1&requested_output=video", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/curation/handoff", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        media_item_ids: ["media_video"],
        project_id: "project 1",
        requested_output: "video",
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/curation/handoff/media%2Fvideo", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        review_status: "accepted",
        project_id: "project 1",
        requested_output: "video",
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/curation/reject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_item_ids: ["media_audio"] }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(6, "http://engine.test/curation/audio/restore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_item_ids: ["media_audio"] }),
    });
  });

  it("surfaces engine detail messages for failed requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "WebP is not supported" }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await expect(
      client.listTrainingTargets(),
    ).rejects.toThrow("WebP is not supported");
  });

  it("loads and installs the identity runtime", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ backend: "opencv-sface", installed: true, ready: true }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.getIdentityStatus();
    await client.installIdentityModels();

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/identity/status", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/identity/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
  });

  it("persists and analyzes trusted voice anchors", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        project_id: "project 1",
        anchor_media_item_ids: ["voice/1"],
        evidence: {},
      }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.getVoiceIdentityStatus();
    await client.getVoiceIdentityProfile("project 1");
    await client.setVoiceIdentityAnchors("project 1", ["voice/1"]);
    await client.confirmVoiceIdentitySample("project 1", "voice/1", "Mary", "voice");
    await client.analyzeVoiceIdentity("project 1", ["voice/1", "voice/2"]);

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/identity/voice/status", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/character-projects/project%201/voice-identity", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/character-projects/project%201/voice-identity/anchors", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_item_ids: ["voice/1"] }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/character-projects/project%201/voice-identity/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        media_item_id: "voice/1",
        subject_label: "Mary",
        requested_output: "voice",
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/character-projects/project%201/voice-identity/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_item_ids: ["voice/1", "voice/2"] }),
    });
  });

  it("stages bulk voice decisions and rescores without retranscription", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ project_id: "project 1", segments: {} }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.bulkUpdateVoiceDatasetSegments("project 1", {
      "segment/1": "approved",
      "segment/2": "rejected",
    });
    await client.rescoreVoiceDataset("project 1");
    await client.analyzeVoiceDatasetQuality("project 1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://engine.test/character-projects/project%201/voice-dataset/segments/bulk-status",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decisions: { "segment/1": "approved", "segment/2": "rejected" } }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://engine.test/character-projects/project%201/voice-dataset/rescore",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://engine.test/character-projects/project%201/voice-dataset/quality-gate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
  });

  it("starts a persistent curation analysis job", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "processing_ai_1",
        job_type: "curation_analysis",
        source_media_item_ids: ["media_1"],
        options: {},
        status: "queued",
        progress_message: "Queued",
        errors: [],
        derived_media_items: [],
        curation_analyses: [],
        created_at: "2026-07-10T00:00:00Z",
      }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.createCurationAnalysisJob(["media_1"]);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/curation/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_item_ids: ["media_1"] }),
    });
  });

  it("persists face choice and materializes an approved crop", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "character_project_1" }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);
    const rect = { x: 0.2, y: 0.1, width: 0.5, height: 0.5 };

    await client.selectCharacterProjectFace("project 1", "media/1", 2);
    await client.updateCharacterProjectCrop("project 1", "crop/1", {
      rect,
      status: "approved",
    });
    await client.materializeCharacterProjectCrop("project 1", "crop/1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://engine.test/character-projects/project%201/observations/media%2F1/face",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ face_index: 2 }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://engine.test/character-projects/project%201/crops/crop%2F1",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rect, status: "approved" }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://engine.test/character-projects/project%201/crops/crop%2F1/materialize",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
  });

  it("compiles, reviews, freezes, and exports dataset snapshots", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "dataset_snapshot_1" }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.listDatasetSnapshots("project 1");
    await client.compileCharacterDataset("project 1");
    await client.updateDatasetItem("snapshot 1", "item/1", {
      caption: "trigger, smiling portrait",
      status: "approved",
    });
    await client.updateDatasetModelCard!("snapshot 1", {
      display_name: "Mary Character",
      license: "CC-BY-4.0",
      recommended_strength: 0.85,
    });
    await client.bulkUpdateDatasetItems("snapshot 1", "excluded", ["item/2"]);
    await client.freezeDatasetSnapshot("snapshot 1");
    await client.exportDatasetSnapshotRunComfy("snapshot 1", "/tmp/export");

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://engine.test/dataset-snapshots?project_id=project%201",
      "http://engine.test/character-projects/project%201/dataset/compile",
      "http://engine.test/dataset-snapshots/snapshot%201/items/item%2F1",
      "http://engine.test/dataset-snapshots/snapshot%201/model-card",
      "http://engine.test/dataset-snapshots/snapshot%201/items/bulk-status",
      "http://engine.test/dataset-snapshots/snapshot%201/freeze",
      "http://engine.test/dataset-snapshots/snapshot%201/export/runcomfy",
    ]);
    expect(fetchMock.mock.calls[3]?.[1]?.body).toBe(
      JSON.stringify({
        display_name: "Mary Character",
        license: "CC-BY-4.0",
        recommended_strength: 0.85,
      }),
    );
    expect(fetchMock.mock.calls[4]?.[1]?.body).toBe(
      JSON.stringify({ status: "excluded", item_ids: ["item/2"] }),
    );
    expect(fetchMock.mock.calls[6]?.[1]?.body).toBe(
      JSON.stringify({ output_dir: "/tmp/export" }),
    );
  });

  it("opens the engine-backed native folder selector", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ path: "/tmp/package" }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await expect(client.pickDirectory!()).resolves.toEqual({ path: "/tmp/package" });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/system/folders/select",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
  });

  it("selects a model-specific training target when compiling", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.listTrainingTargets();
    await client.listModelIntentRecipes?.();
    await client.compileCharacterDataset("project 1", "runcomfy_qwen_image_character");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/training-targets", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://engine.test/model-intent-recipes",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://engine.test/character-projects/project%201/dataset/compile",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ training_target_profile_id: "runcomfy_qwen_image_character" }),
      },
    );
  });

  it("lists providers and creates a scoped vision caption job", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "caption_job_1", status: "queued" }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);
    const request = {
      item_ids: ["item/1"],
      provider_id: "openai",
      provider_label: "OpenAI",
      dialect: "responses" as const,
      base_url: "https://api.openai.com/v1",
      model: "gpt-5",
      api_key: "job-secret",
    };

    await client.listCaptionProviders();
    await client.startGrokOAuthLogin();
    await client.listCaptionJobs("snapshot 1");
    await client.getCaptionJob("job/1");
    await client.cancelCaptionJob("job/1");
    await client.createCaptionJob("snapshot 1", request);

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      "http://engine.test/caption/providers",
      "http://engine.test/caption/providers/grok-oauth/login",
      "http://engine.test/caption-jobs?snapshot_id=snapshot%201",
      "http://engine.test/caption-jobs/job%2F1",
      "http://engine.test/caption-jobs/job%2F1/cancel",
      "http://engine.test/dataset-snapshots/snapshot%201/caption-jobs",
    ]);
    expect(fetchMock.mock.calls[1]?.[1]?.body).toBe(JSON.stringify({}));
    expect(fetchMock.mock.calls[4]?.[1]?.body).toBe(JSON.stringify({}));
    expect(fetchMock.mock.calls[5]?.[1]?.body).toBe(JSON.stringify(request));
  });

  it("posts local scan roots to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_1", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.scanLocalIngress(["/tmp/media"], true);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/local/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roots: ["/tmp/media"], recursive: true }),
    });
  });

  it("posts browser local uploads to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_upload", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);
    const rootFile = new File(["image"], "portrait.png", { type: "image/png" });
    const nestedFile = new File(["image"], "nested.png", { type: "image/png" });
    Object.defineProperty(nestedFile, "webkitRelativePath", {
      value: "session/nested.png",
    });

    await client.uploadLocalIngress([rootFile, nestedFile]);

    const request = fetchMock.mock.calls[0]?.[1];
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://engine.test/ingress/local/upload-scan");
    expect(request?.method).toBe("POST");
    expect(request?.headers).toBeUndefined();
    expect(request?.body).toBeInstanceOf(FormData);
    const body = request?.body as FormData;
    const uploaded = body.getAll("files") as File[];
    expect(uploaded).toHaveLength(2);
    expect(uploaded[0].name).toBe("portrait.png");
    expect(uploaded[1].name).toBe("session/nested.png");
  });

  it("posts instagram helper payloads to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_ig", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);
    const payload = { helper_version: "fixture", media: [] };

    await client.scanInstagramHelperPayload(payload, true);

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/instagram/helper-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        payload,
        include_video_posters_as_image_candidates: true,
      }),
    });
  });

  it("posts instagram browser scans to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_browser", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.scanInstagramBrowserUrl(
      "https://www.instagram.com/reel/example/",
      "chrome",
      8,
      "cursor_2",
      "tagged",
    );

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/instagram/browser-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: "https://www.instagram.com/reel/example/",
        browser: "chrome",
        limit: 8,
        cursor: "cursor_2",
        scan_mode: "tagged",
      }),
    });
  });

  it("posts TikTok browser scans to the engine", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "scan_tiktok", candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.scanTikTokBrowserUrl?.(
      "https://www.tiktok.com/@subject",
      "firefox",
      12,
      "24",
      "2026-01-01",
    );

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/tiktok/browser-scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: "https://www.tiktok.com/@subject",
        browser: "firefox",
        limit: 12,
        cursor: "24",
        date_from: "2026-01-01",
      }),
    });
  });

  it("creates, polls, resumes, and cancels persisted social acquisition jobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "social/1", status: "queued" }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);
    const request = {
      provider: "instagram" as const,
      url: "https://www.instagram.com/subject",
      browser: "chrome",
      limit: 24,
      scan_mode: "all" as const,
    };

    await client.createSocialAcquisitionJob?.(request);
    await client.listSocialAcquisitionJobs?.();
    await client.getSocialAcquisitionJob?.("social/1");
    await client.resumeSocialAcquisitionJob?.("social/1");
    await client.cancelSocialAcquisitionJob?.("social/1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/ingress/social-acquisitions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/ingress/social-acquisitions", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/ingress/social-acquisitions/social%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/ingress/social-acquisitions/social%2F1/resume", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/ingress/social-acquisitions/social%2F1/cancel", expect.objectContaining({ method: "POST" }));
  });

  it("lists stored ingress candidates by source", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ candidates: [], errors: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.listIngressCandidates("instagram");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/ingress/candidates?source_kind=instagram",
      {
        method: "GET",
        headers: { "Content-Type": "application/json" },
      },
    );
  });

  it("creates an ingress job", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "job_1", source_kind: "local", candidate_ids: [] }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.createIngressJob({
      source_kind: "local",
      candidate_ids: ["candidate_1"],
      reviewed_candidate_ids: ["candidate_1", "candidate_2"],
    });

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/ingress/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_kind: "local",
        candidate_ids: ["candidate_1"],
        reviewed_candidate_ids: ["candidate_1", "candidate_2"],
      }),
    });
  });

  it("creates a processing job", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_1"],
        options: {
          frames_per_second: 2,
          max_frame_count: 48,
          extract_audio: true,
          generate_frames: true,
        },
        status: "queued",
        progress_message: "Queued",
        errors: [],
        derived_media_items: [{ id: "media_frame_1", media_type: "image" }],
        created_at: "2026-07-09T12:00:00Z",
        started_at: null,
        completed_at: null,
      }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    const result = await client.createProcessingJob({
      job_type: "video_breakdown",
      source_media_item_ids: ["media_1"],
      options: {
        frames_per_second: 2,
        max_frame_count: 48,
        extract_audio: true,
        generate_frames: true,
      },
    });

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/processing/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_type: "video_breakdown",
        source_media_item_ids: ["media_1"],
        options: {
          frames_per_second: 2,
          max_frame_count: 48,
          extract_audio: true,
          generate_frames: true,
        },
      }),
    });
    expect(result.id).toBe("processing_1");
  });

  it("lists processing jobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [
        {
          id: "processing_1",
          job_type: "video_breakdown",
          source_media_item_ids: ["media_1"],
          options: {},
          status: "running",
          progress_message: "Extracting frames",
          errors: [],
          derived_media_items: [],
          created_at: "2026-07-09T12:00:00Z",
          started_at: "2026-07-09T12:01:00Z",
          completed_at: null,
        },
      ],
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    const result = await client.listProcessingJobs();

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/processing/jobs", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(result[0].status).toBe("running");
  });

  it("gets a processing job by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_1"],
        options: {},
        status: "complete",
        progress_message: "Done",
        errors: [],
        derived_media_items: [{ id: "audio_1", media_type: "audio" }],
        created_at: "2026-07-09T12:00:00Z",
        started_at: "2026-07-09T12:01:00Z",
        completed_at: "2026-07-09T12:02:00Z",
      }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    const result = await client.getProcessingJob("processing_1");

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/processing/jobs/processing_1", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(result.derived_media_items[0].id).toBe("audio_1");
  });

  it("processes an existing processing job by id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_1"],
        options: {},
        status: "running",
        progress_message: "Breaking down video media",
        errors: [],
        derived_media_items: [],
        created_at: "2026-07-09T12:00:00Z",
        started_at: "2026-07-09T12:01:00Z",
        completed_at: null,
      }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    const result = await client.processProcessingJob("processing_1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/processing/jobs/processing_1/process",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      },
    );
    expect(result.status).toBe("running");
  });

  it("updates reviewed video keepers", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_1"],
        options: { intelligent_selection: true },
        status: "complete",
        progress_message: "Saved 2 reviewed keeper frames",
        errors: [],
        derived_media_items: [],
        video_analyses: [],
        created_at: "2026-07-09T12:00:00Z",
      }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    const result = await client.updateVideoKeepers("processing_1", ["frame_1", "frame_2"]);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/processing/jobs/processing_1/keepers",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frame_ids: ["frame_1", "frame_2"] }),
      },
    );
    expect(result.progress_message).toBe("Saved 2 reviewed keeper frames");
  });

  it("commits reviewed frames and trimmed video clips", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        id: "processing_1",
        job_type: "video_breakdown",
        source_media_item_ids: ["media_1"],
        options: { intelligent_selection: true },
        status: "complete",
        progress_message: "Committed 1 frames and 1 video clips",
        errors: [],
        derived_media_items: [],
        video_analyses: [],
        created_at: "2026-07-09T12:00:00Z",
      }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);
    const request = {
      frame_ids: ["frame_1"],
      clips: [
        {
          clip_id: "clip_1",
          start_seconds: 1.2,
          end_seconds: 3.8,
          decision: "keep" as const,
        },
      ],
    };

    await client.commitVideoBreakdown("processing_1", request);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://engine.test/processing/jobs/processing_1/commit",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
    );
  });

  it("persists character project candidates and manual review decisions", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "character_project_1", observations: {}, health: {} }),
    });
    const client = createEngineClient("http://engine.test", fetchMock);

    await client.addCharacterProjectCandidates("character_project_1", ["media_1"]);
    await client.updateCharacterProjectObservation("character_project_1", "media_1", {
      review_status: "accepted",
      view: "face",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://engine.test/character-projects/character_project_1/candidates",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ media_item_ids: ["media_1"] }),
      },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://engine.test/character-projects/character_project_1/observations/media_1",
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_status: "accepted", view: "face" }),
      },
    );
  });

  it("builds engine asset URLs for local vault paths", () => {
    const client = createEngineClient("http://engine.test/");

    expect(client.assetUrl("/tmp/vault/previews/thumb one.jpg")).toBe(
      "http://engine.test/assets/file?path=%2Ftmp%2Fvault%2Fpreviews%2Fthumb%20one.jpg",
    );
  });

  it("creates and controls persisted RunComfy training runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "training/run 1", status: "queued", artifacts: [] }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listTrainingRuns("snapshot 1");
    await client.createTrainingRun({
      snapshot_id: "snapshot 1",
      config_file: "folder_path: /app/ai-toolkit/datasets/{dataset_name}",
      gpu_type: "ADA_80_PLUS",
      api_token: "session-only",
    });
    await client.refreshTrainingRun("training/run 1", "session-only");
    await client.resumeTrainingRun("training/run 1", "session-only");
    await client.cancelTrainingRun("training/run 1", "session-only");
    await client.listModelArtifacts("snapshot 1");
    await client.registerTrainingArtifacts("training/run 1");
    await client.listComfyInstallations();
    await client.installModelArtifact("artifact/1", "/tmp/ComfyUI");
    await client.listModelReleaseCandidates("project 1", "video");
    await client.selectModelRelease("artifact/1");
    await client.getComfyRuntimeStatus("/tmp/ComfyUI", "http://127.0.0.1:8188");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/training-runs?snapshot_id=snapshot%201", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/training-runs/runcomfy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        snapshot_id: "snapshot 1",
        config_file: "folder_path: /app/ai-toolkit/datasets/{dataset_name}",
        gpu_type: "ADA_80_PLUS",
        api_token: "session-only",
      }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/training-runs/training%2Frun%201/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_token: "session-only" }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/training-runs/training%2Frun%201/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_token: "session-only" }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/training-runs/training%2Frun%201/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_token: "session-only" }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(6, "http://engine.test/model-artifacts?snapshot_id=snapshot%201", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(7, "http://engine.test/training-runs/training%2Frun%201/register-artifacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(8, "http://engine.test/comfyui/installations", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(9, "http://engine.test/model-artifacts/artifact%2F1/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comfy_root: "/tmp/ComfyUI" }),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(10, "http://engine.test/model-artifacts/release-candidates?project_id=project+1&modality=video", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(11, "http://engine.test/model-artifacts/artifact%2F1/select-release", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    expect(fetchMock).toHaveBeenNthCalledWith(12, "http://engine.test/comfyui/runtime-status?comfy_root=%2Ftmp%2FComfyUI&base_url=http%3A%2F%2F127.0.0.1%3A8188", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
  });

  it("compiles, reviews, freezes, and exports video datasets", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "video_snapshot_1", items: {}, balance: {} }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listVideoDatasetCandidates("project 1");
    await client.listVideoDatasetSnapshots("project 1");
    await client.compileVideoDataset("project 1", ["clip/1"], "comfyui_minimax_h3_ref2va", ["image/1"], ["audio/1"]);
    await client.updateVideoDatasetItem("video snapshot", "clip/1", { status: "approved" });
    await client.bulkUpdateVideoDataset("video snapshot", "excluded");
    await client.freezeVideoDataset("video snapshot");
    await client.exportVideoDataset("video snapshot", "/tmp/video dataset");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/video-dataset/candidates?project_id=project%201", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/video-dataset-snapshots?project_id=project%201", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/video-dataset-snapshots/compile", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        project_id: "project 1",
        media_item_ids: ["clip/1"],
        target_profile_id: "comfyui_minimax_h3_ref2va",
        reference_image_media_item_ids: ["image/1"],
        reference_audio_media_item_ids: ["audio/1"],
      }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/video-dataset-snapshots/video%20snapshot/items/clip%2F1", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ status: "approved" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/video-dataset-snapshots/video%20snapshot/bulk-status", expect.objectContaining({
      body: JSON.stringify({ status: "excluded" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(6, "http://engine.test/video-dataset-snapshots/video%20snapshot/freeze", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(7, "http://engine.test/video-dataset-snapshots/video%20snapshot/export", expect.objectContaining({
      body: JSON.stringify({ output_dir: "/tmp/video dataset" }),
    }));
  });

  it("compiles and restores ID-LoRA input contracts", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "id_lora_1", examples: {}, voice_references: {} }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listIdLoraManifests("project 1");
    await client.getIdLoraManifest("manifest/1");
    await client.compileIdLoraManifest("project 1", "video snapshot");
    await client.exportIdLoraManifest("manifest/1", "/tmp/id lora");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/id-lora-manifests?project_id=project%201", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/id-lora-manifests/manifest%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/id-lora-manifests/compile", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ project_id: "project 1", video_snapshot_id: "video snapshot" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/id-lora-manifests/manifest%2F1/export", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ output_dir: "/tmp/id lora" }),
    }));
  });

  it("creates and monitors LoRA benchmark runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "benchmark/1", status: "queued" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.getBenchmarkSuite();
    await client.prepareBenchmarkWorkspace("project 1", "/tmp/evaluation root");
    await client.listBenchmarkRuns("project 1");
    await client.getBenchmarkRun("benchmark/1");
    await client.createBenchmarkRun({ project_id: "project 1", baseline_dir: "/tmp/base", lora_dir: "/tmp/lora", artifact_id: "artifact 1" });
    await client.reviewBenchmarkCase("benchmark/1", "speech/closeup", "rejected", "Lip sync drifts");
    await client.retryBenchmarkGenerationRun("generation/1", ["speech_closeup"], "session-token");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/benchmark-suite", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/benchmark-suite/prepare", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ project_id: "project 1", output_dir: "/tmp/evaluation root" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/benchmark-runs?project_id=project%201", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/benchmark-runs/benchmark%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/benchmark-runs", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ project_id: "project 1", baseline_dir: "/tmp/base", lora_dir: "/tmp/lora", artifact_id: "artifact 1" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(6, "http://engine.test/benchmark-runs/benchmark%2F1/cases/speech%2Fcloseup/review", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ decision: "rejected", note: "Lip sync drifts" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(7, "http://engine.test/benchmark-generation-runs/generation%2F1/retry", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ case_ids: ["speech_closeup"], api_token: "session-token" }),
    }));
  });

  it("creates and monitors RunComfy benchmark generation runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "generation/1", status: "queued" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listBenchmarkGenerationRuns("project 1");
    await client.getBenchmarkGenerationRun("generation/1");
    await client.createBenchmarkGenerationRun({
      project_id: "project 1",
      workspace_root: "/tmp/evaluation",
      model_id: "provider/video-model",
      lora_path: "person.safetensors",
      seed_base: 42,
      auto_evaluate: true,
      api_token: "session-token",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/benchmark-generation-runs?project_id=project%201", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/benchmark-generation-runs/generation%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/benchmark-generation-runs/runcomfy", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        project_id: "project 1",
        workspace_root: "/tmp/evaluation",
        model_id: "provider/video-model",
        lora_path: "person.safetensors",
        seed_base: 42,
        auto_evaluate: true,
        api_token: "session-token",
      }),
    }));
  });

  it("creates and monitors RunComfy benchmark generation runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "generation/1", status: "queued" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listBenchmarkGenerationRuns("project 1");
    await client.getBenchmarkGenerationRun("generation/1");
    await client.createBenchmarkGenerationRun({
      project_id: "project 1",
      workspace_root: "/tmp/evaluation",
      model_id: "provider/video-model",
      lora_path: "person.safetensors",
      artifact_id: "artifact 1",
      baseline_payload: { prompt: "$PROMPT", seed: "$SEED" },
      lora_payload: { prompt: "$PROMPT", seed: "$SEED", lora: { path: "$LORA_PATH" } },
      seed_base: 424242,
      auto_evaluate: true,
      api_token: "session-token",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/benchmark-generation-runs?project_id=project%201", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/benchmark-generation-runs/generation%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/benchmark-generation-runs/runcomfy", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        project_id: "project 1",
        workspace_root: "/tmp/evaluation",
        model_id: "provider/video-model",
        lora_path: "person.safetensors",
        artifact_id: "artifact 1",
        baseline_payload: { prompt: "$PROMPT", seed: "$SEED" },
        lora_payload: { prompt: "$PROMPT", seed: "$SEED", lora: { path: "$LORA_PATH" } },
        seed_base: 424242,
        auto_evaluate: true,
        api_token: "session-token",
      }),
    }));
  });

  it("creates RunPod benchmark generation runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "generation/1", provider: "runpod_serverless", status: "queued" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.createRunPodBenchmarkGenerationRun({
      project_id: "project 1",
      workspace_root: "/tmp/evaluation",
      endpoint_id: "endpoint-video-1",
      lora_path: "https://assets.test/person.safetensors",
      baseline_payload: { input: { prompt: "$PROMPT", seed: "$SEED" } },
      lora_payload: { input: { prompt: "$PROMPT", seed: "$SEED", lora: { path: "$LORA_PATH" } } },
      api_token: "runpod-secret",
    });

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/benchmark-generation-runs/runpod", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        project_id: "project 1",
        workspace_root: "/tmp/evaluation",
        endpoint_id: "endpoint-video-1",
        lora_path: "https://assets.test/person.safetensors",
        baseline_payload: { input: { prompt: "$PROMPT", seed: "$SEED" } },
        lora_payload: { input: { prompt: "$PROMPT", seed: "$SEED", lora: { path: "$LORA_PATH" } } },
        api_token: "runpod-secret",
      }),
    }));
  });

  it("creates and monitors image LoRA benchmark runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "image/1", status: "queued" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.getImageBenchmarkSuite();
    await client.prepareImageBenchmarkWorkspace("project 1", "/tmp/image evaluation");
    await client.listBenchmarkGenerationRuns("project 1", "image");
    await client.createImageBenchmarkGenerationRun({ project_id: "project 1", workspace_root: "/tmp/image", model_id: "provider/image", lora_path: "person.safetensors" });
    await client.createRunPodImageBenchmarkGenerationRun({ project_id: "project 1", workspace_root: "/tmp/image", endpoint_id: "endpoint-1", lora_path: "person.safetensors" });
    await client.listImageBenchmarkRuns("project 1");
    await client.getImageBenchmarkRun("image/1");
    await client.createImageBenchmarkRun({ project_id: "project 1", baseline_dir: "/tmp/base", lora_dir: "/tmp/lora", artifact_id: "artifact 1" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/image-benchmark-suite", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/image-benchmark-suite/prepare", expect.objectContaining({ method: "POST", body: JSON.stringify({ project_id: "project 1", output_dir: "/tmp/image evaluation" }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/benchmark-generation-runs?project_id=project%201&benchmark_kind=image", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/image-benchmark-generation-runs/runcomfy", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/image-benchmark-generation-runs/runpod", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(6, "http://engine.test/image-benchmark-runs?project_id=project%201", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(7, "http://engine.test/image-benchmark-runs/image%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(8, "http://engine.test/image-benchmark-runs", expect.objectContaining({ method: "POST", body: JSON.stringify({ project_id: "project 1", baseline_dir: "/tmp/base", lora_dir: "/tmp/lora", artifact_id: "artifact 1" }) }));
  });

  it("creates a RunPod network-volume training bundle", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "bundle-1", provider: "runpod" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.createRunPodBundle({
      source_export_path: "/tmp/image-export",
      output_path: "/tmp/runpod-bundle",
      modality: "image",
      trigger_token: "person_token",
      fingerprint: "abcdef",
      training_target_profile_id: "runcomfy_flux1_dev_character",
      remote_root: "/workspace/lorasuite",
      endpoint_id: "endpoint-1",
    });

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/runpod-bundles", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        source_export_path: "/tmp/image-export",
        output_path: "/tmp/runpod-bundle",
        modality: "image",
        trigger_token: "person_token",
        fingerprint: "abcdef",
        training_target_profile_id: "runcomfy_flux1_dev_character",
        remote_root: "/workspace/lorasuite",
        endpoint_id: "endpoint-1",
      }),
    }));
  });

  it("lists and provisions RunPod infrastructure profiles", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "infra-1", status: "ready" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listRunPodInfrastructureProfiles();
    await client.provisionRunPodInfrastructure({
      image_name: "docker.io/example/worker:sha-123",
      data_center_id: "US-KS-2",
      runtime_environment: { HF_TOKEN: "session-hf-token" },
      api_token: "session-runpod-key",
    });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/runpod-infrastructure-profiles", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/runpod-infrastructure-profiles/provision", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        image_name: "docker.io/example/worker:sha-123",
        data_center_id: "US-KS-2",
        runtime_environment: { HF_TOKEN: "session-hf-token" },
        api_token: "session-runpod-key",
      }),
    }));
  });

  it("creates and monitors RunPod model bootstrap runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "bootstrap-1", status: "running" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listRunPodModelBootstrapRuns("endpoint/1", "runpod_fish_speech_s2_voice_lora");
    await client.getRunPodModelBootstrapRun("bootstrap/1");
    await client.createRunPodModelBootstrapRun({ endpoint_id: "endpoint/1", training_target_profile_id: "runpod_fish_speech_s2_voice_lora", api_token: "session-key" });
    await client.refreshRunPodModelBootstrapRun("bootstrap/1", "session-key");
    await client.cancelRunPodModelBootstrapRun("bootstrap/1", "session-key");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/runpod-model-bootstrap-runs?endpoint_id=endpoint%2F1&training_target_profile_id=runpod_fish_speech_s2_voice_lora", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/runpod-model-bootstrap-runs/bootstrap%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/runpod-model-bootstrap-runs", expect.objectContaining({ method: "POST", body: JSON.stringify({ endpoint_id: "endpoint/1", training_target_profile_id: "runpod_fish_speech_s2_voice_lora", api_token: "session-key" }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/runpod-model-bootstrap-runs/bootstrap%2F1/refresh", expect.objectContaining({ method: "POST", body: JSON.stringify({ api_token: "session-key" }) }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/runpod-model-bootstrap-runs/bootstrap%2F1/cancel", expect.objectContaining({ method: "POST", body: JSON.stringify({ api_token: "session-key" }) }));
  });

  it("launches and monitors a RunPod Serverless training run", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "run-1", provider: "runpod" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listRunPodTrainingRuns("/tmp/runpod bundle");
    await client.createRunPodTrainingRun({ bundle_path: "/tmp/runpod-bundle", endpoint_id: "endpoint-1", api_token: "session-key" });
    await client.refreshRunPodTrainingRun("run/1", "session-key");
    await client.cancelRunPodTrainingRun("run/1", "session-key");
    await client.downloadRunPodTrainingArtifacts("run/1", {
      output_dir: "/tmp/artifacts", volume_id: "volume-1", s3_endpoint: "https://s3.example/", datacenter: "US-CA-2",
    });
    await client.registerRunPodTrainingArtifacts("run/1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/runpod-training-runs?bundle_path=%2Ftmp%2Frunpod%20bundle", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/runpod-training-runs", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ bundle_path: "/tmp/runpod-bundle", endpoint_id: "endpoint-1", api_token: "session-key" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/runpod-training-runs/run%2F1/refresh", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ api_token: "session-key" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/runpod-training-runs/run%2F1/cancel", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ api_token: "session-key" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/runpod-training-runs/run%2F1/download-artifacts", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ output_dir: "/tmp/artifacts", volume_id: "volume-1", s3_endpoint: "https://s3.example/", datacenter: "US-CA-2" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(6, "http://engine.test/runpod-training-runs/run%2F1/register-artifacts", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({}),
    }));
  });

  it("checks RunPod endpoint readiness before launch", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "preflight-1", ready: true }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listRunPodPreflightReports("/tmp/runpod bundle", "endpoint/1");
    await client.createRunPodPreflightReport({ bundle_path: "/tmp/runpod-bundle", endpoint_id: "endpoint/1", api_token: "session-key" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/runpod-preflight-reports?bundle_path=%2Ftmp%2Frunpod+bundle&endpoint_id=endpoint%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/runpod-preflight-reports", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ bundle_path: "/tmp/runpod-bundle", endpoint_id: "endpoint/1", api_token: "session-key" }),
    }));
  });

  it("queues, monitors, and resumes RunPod bundle uploads", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "upload-1", status: "queued" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listRunPodBundleUploadJobs("/tmp/runpod bundle");
    await client.getRunPodBundleUploadJob("upload/1");
    await client.createRunPodBundleUploadJob({
      bundle_path: "/tmp/runpod-bundle", volume_id: "volume-1", s3_endpoint: "https://s3.example/", datacenter: "US-CA-2",
      access_key: "access-key", secret_key: "secret-key",
    });
    await client.resumeRunPodBundleUploadJob("upload/1", "access-key", "secret-key");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/runpod-bundle-upload-jobs?bundle_path=%2Ftmp%2Frunpod%20bundle", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/runpod-bundle-upload-jobs/upload%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/runpod-bundle-upload-jobs", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/runpod-bundle-upload-jobs/upload%2F1/resume", expect.objectContaining({
      method: "POST", body: JSON.stringify({ access_key: "access-key", secret_key: "secret-key" }),
    }));
  });

  it("creates, monitors, recommends, and selects voice artifact evaluations", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "voice-run-1" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listVoiceArtifactEvaluations("project/1");
    await client.getVoiceArtifactEvaluation("voice/run");
    await client.getRecommendedVoiceArtifactEvaluation("project/1");
    await client.createVoiceArtifactEvaluation({ project_id: "project/1", artifact_id: "artifact-1", samples_dir: "/tmp/voice samples" });
    await client.selectVoiceArtifactEvaluation("voice/run");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/voice-artifact-evaluations?project_id=project%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/voice-artifact-evaluations/voice%2Frun", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/voice-artifact-evaluations/recommended?project_id=project%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/voice-artifact-evaluations", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ project_id: "project/1", artifact_id: "artifact-1", samples_dir: "/tmp/voice samples" }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/voice-artifact-evaluations/voice%2Frun/select", expect.objectContaining({ method: "POST", body: JSON.stringify({}) }));
  });

  it("creates and monitors ID-LoRA zero-shot evaluations", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ id: "id-eval-1" }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listIdLoraEvaluations("project/1");
    await client.getIdLoraEvaluation("evaluation/1");
    await client.createIdLoraEvaluation("runpod/1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/id-lora-evaluations?project_id=project%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/id-lora-evaluations/evaluation%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/id-lora-evaluations", expect.objectContaining({ method: "POST", body: JSON.stringify({ runpod_run_id: "runpod/1" }) }));
  });

  it("loads the persisted training workflow planner for a project", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ project_id: "project/1", lanes: [] }) });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.getTrainingWorkflow("project/1");

    expect(fetchMock).toHaveBeenCalledWith("http://engine.test/training-workflow/project%2F1", {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
  });

  it("compares artifact revisions and records explicit improvement decisions", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: "comparison-1", status: "draft" }),
    });
    const client = createEngineClient("http://engine.test/", fetchMock);

    await client.listArtifactComparisons?.({ projectId: "project/1", benchmarkKind: "image" });
    await client.createArtifactComparison?.({
      project_id: "project/1",
      benchmark_kind: "image",
      candidate_artifact_id: "candidate/1",
      reference_artifact_id: "reference/1",
    });
    await client.listImprovementRequests?.({ projectId: "project/1", status: "draft" });
    await client.createImprovementRequest?.("comparison/1");
    await client.decideImprovementRequest?.("request/1", "approved", "Build revision two.");
    await client.listDatasetRevisions?.("project/1");
    await client.materializeDatasetRevision?.("request/1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "http://engine.test/artifact-comparisons?project_id=project%2F1&benchmark_kind=image", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://engine.test/artifact-comparisons", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        project_id: "project/1",
        benchmark_kind: "image",
        candidate_artifact_id: "candidate/1",
        reference_artifact_id: "reference/1",
      }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://engine.test/improvement-requests?project_id=project%2F1&status=draft", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(4, "http://engine.test/artifact-comparisons/comparison%2F1/improvement-request", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenNthCalledWith(5, "http://engine.test/improvement-requests/request%2F1", expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ decision: "approved", note: "Build revision two." }),
    }));
    expect(fetchMock).toHaveBeenNthCalledWith(6, "http://engine.test/dataset-revisions?project_id=project%2F1", expect.objectContaining({ method: "GET" }));
    expect(fetchMock).toHaveBeenNthCalledWith(7, "http://engine.test/improvement-requests/request%2F1/materialize-revision", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({}),
    }));
  });
});
