"use client";

import { useRef, useState } from "react";
import type { Identification, Platform, PublishResponse, UploadResponse } from "@/types/api";
import { uploadImage } from "@/api/upload";
import { publishListing } from "@/api/publish";
import UploadScreen from "@/components/UploadScreen";
import AnalyzingScreen from "@/components/AnalyzingScreen";
import ResultsScreen from "@/components/ResultsScreen";
import PublishedScreen from "@/components/PublishedScreen";

type AppState =
  | { screen: "upload" }
  | { screen: "analyzing"; imageUrl: string; file: File }
  | { screen: "results"; imageUrl: string; data: UploadResponse }
  | {
      screen: "published";
      platform: Platform;
      publishResponse: PublishResponse;
      results: UploadResponse;
    };

export default function Page() {
  const [state, setState] = useState<AppState>({ screen: "upload" });
  // Incremented on every reset so a stale upload promise doesn't clobber state
  const uploadGenRef = useRef(0);

  async function handleFileSelected(file: File, imageUrl: string) {
    const gen = ++uploadGenRef.current;
    setState({ screen: "analyzing", imageUrl, file });
    try {
      const data = await uploadImage(file);
      if (gen !== uploadGenRef.current) return;
      setState({ screen: "results", imageUrl, data });
    } catch {
      if (gen !== uploadGenRef.current) return;
      setState({ screen: "upload" });
    }
  }

  async function handlePublish(platform: Platform, finalFields: Identification) {
    if (state.screen !== "results") return;
    const { data } = state;
    try {
      const publishResponse = await publishListing({
        listing_id: data.listing_id,
        platform,
        final_fields: finalFields,
      });
      // Open the prefill URL immediately before state update
      window.open(publishResponse.prefill_url, "_blank");
      setState({
        screen: "published",
        platform,
        publishResponse,
        results: data,
      });
    } catch {
      // Stay on results if publish fails
    }
  }

  function handleReset() {
    uploadGenRef.current++; // invalidate any in-flight upload
    setState({ screen: "upload" });
  }

  if (state.screen === "upload") {
    return <UploadScreen onFileSelected={handleFileSelected} />;
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

  if (state.screen === "published") {
    return (
      <PublishedScreen
        platform={state.platform}
        publishResponse={state.publishResponse}
        results={state.results}
        onReset={handleReset}
      />
    );
  }
}
