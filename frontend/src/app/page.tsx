"use client";

import { useRef, useState } from "react";
import type { Identification, Platform, UploadResponse } from "@/types/api";
import { uploadImage } from "@/api/upload";
import { draftListing } from "@/api/publish";
import UploadScreen from "@/components/UploadScreen";
import AnalyzingScreen from "@/components/AnalyzingScreen";
import ResultsScreen from "@/components/ResultsScreen";
import PublishedScreen from "@/components/PublishedScreen";
import PublishingScreen from "@/components/PublishingScreen";
import InventoryScreen from "@/components/InventoryScreen";

type AppState =
  | { screen: "upload" }
  | { screen: "inventory" }
  | { screen: "analyzing"; imageUrl: string; file: File }
  | { screen: "results"; imageUrl: string; data: UploadResponse }
  | { screen: "publishing"; imageUrl: string; data: UploadResponse; platform: Platform }
  | {
      screen: "published";
      platform: Platform;
      listingUrl: string;
      results: UploadResponse;
    };

export default function Page() {
  const [state, setState] = useState<AppState>({ screen: "upload" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  // Incremented on every reset so a stale upload promise doesn't clobber state
  const uploadGenRef = useRef(0);

  async function handleFileSelected(file: File, imageUrl: string) {
    const gen = ++uploadGenRef.current;
    setUploadError(null);
    setState({ screen: "analyzing", imageUrl, file });
    try {
      const data = await uploadImage(file);
      if (gen !== uploadGenRef.current) return;
      setState({ screen: "results", imageUrl, data });
    } catch (err) {
      if (gen !== uploadGenRef.current) return;
      setUploadError(
        err instanceof Error ? err.message : "Could not analyze photo. Is the backend running?"
      );
      setState({ screen: "upload" });
    }
  }

  async function handlePublish(platform: Platform, finalFields: Identification) {
    if (state.screen !== "results") return;
    const { data, imageUrl } = state;
    setState({ screen: "publishing", imageUrl, data, platform });
    try {
      const draft = await draftListing({
        listing_id: data.listing_id,
        platform,
        final_fields: finalFields,
      });
      window.open(draft.draft_url, "_blank");
      setState({ screen: "published", platform, listingUrl: draft.draft_url, results: data });
    } catch {
      setState({ screen: "results", imageUrl, data });
    }
  }

  function handleReset() {
    uploadGenRef.current++; // invalidate any in-flight upload
    setUploadError(null);
    setState({ screen: "upload" });
  }

  if (state.screen === "inventory") {
    return <InventoryScreen onBack={() => setState({ screen: "upload" })} />;
  }

  if (state.screen === "upload") {
    return (
      <UploadScreen
        onFileSelected={handleFileSelected}
        onInventory={() => setState({ screen: "inventory" })}
        error={uploadError}
      />
    );
  }

  if (state.screen === "analyzing") {
    return (
      <AnalyzingScreen
        imageUrl={state.imageUrl}
        onCancel={handleReset}
      />
    );
  }

  if (state.screen === "results") {
    return (
      <ResultsScreen
        imageUrl={state.imageUrl}
        data={state.data}
        onPublish={handlePublish}
        onReset={handleReset}
      />
    );
  }

  if (state.screen === "publishing") {
    return <PublishingScreen platform={state.platform} />;
  }

  if (state.screen === "published") {
    return (
      <PublishedScreen
        platform={state.platform}
        listingUrl={state.listingUrl}
        results={state.results}
        onReset={handleReset}
      />
    );
  }
}
