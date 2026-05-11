"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  Identification,
  OnboardingStatus,
  Platform,
  UploadResponse,
} from "@/types/api";
import { uploadImage } from "@/api/upload";
import { pollPublishStatus, publishListing } from "@/api/publish";
import { fetchOnboardingStatus } from "@/api/onboarding";
import { BASE, fetchListingPrediction } from "@/api/inventory";
import UploadScreen from "@/components/UploadScreen";
import AnalyzingScreen from "@/components/AnalyzingScreen";
import ResultsScreen from "@/components/ResultsScreen";
import PublishedScreen, { type PublishOutcome } from "@/components/PublishedScreen";
import PublishingScreen from "@/components/PublishingScreen";
import InventoryScreen from "@/components/InventoryScreen";
import PlatformConnectionBanner from "@/components/PlatformConnectionBanner";
import PlatformLoginModal from "@/components/PlatformLoginModal";

type PublishItem = { platform: Platform; finalFields: Identification };
type PublishProgress = Record<Platform, "pending" | "posted" | "failed">;

type AppState =
  | { screen: "upload" }
  | { screen: "inventory" }
  | {
      screen: "analyzing";
      imageUrl: string;
      file: File;
      labelImageUrl?: string;
      labelFile?: File;
    }
  | {
      screen: "results";
      imageUrl: string;
      data: UploadResponse;
      labelImageUrl?: string;
    }
  | {
      screen: "publishing";
      imageUrl: string;
      data: UploadResponse;
      platforms: Platform[];
      progress: PublishProgress;
      labelImageUrl?: string;
    }
  | {
      screen: "published";
      outcomes: PublishOutcome[];
      results: UploadResponse;
    };

export default function Page() {
  const [state, setState] = useState<AppState>({ screen: "upload" });
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [connectionStatus, setConnectionStatus] = useState<OnboardingStatus | null>(null);
  const [loginModalPlatform, setLoginModalPlatform] = useState<Platform | null>(null);
  // Incremented on every reset so a stale upload promise doesn't clobber state
  const uploadGenRef = useRef(0);

  const refreshStatus = useCallback(async () => {
    try {
      const s = await fetchOnboardingStatus();
      setConnectionStatus(s);
    } catch {
      // Backend down or other error — leave previous state in place; the
      // banner just stays empty rather than flashing a misleading "all good".
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  async function handleSubmit(
    file: File,
    imageUrl: string,
    labelFile?: File,
    labelImageUrl?: string,
  ) {
    const gen = ++uploadGenRef.current;
    setUploadError(null);
    setState({ screen: "analyzing", imageUrl, file, labelImageUrl, labelFile });
    try {
      const data = await uploadImage(file, labelFile);
      if (gen !== uploadGenRef.current) return;
      setState({ screen: "results", imageUrl, data, labelImageUrl });
    } catch (err) {
      if (gen !== uploadGenRef.current) return;
      setUploadError(
        err instanceof Error ? err.message : "Could not analyze photo. Is the backend running?"
      );
      setState({ screen: "upload" });
    }
  }

  async function _runPublishes(
    listingId: string,
    items: PublishItem[],
    data: UploadResponse,
    imageUrl: string,
    labelImageUrl?: string,
  ): Promise<void> {
    if (items.length === 0) return;
    setUploadError(null);
    const initialProgress = Object.fromEntries(
      items.map((i) => [i.platform, "pending"]),
    ) as PublishProgress;
    setState({
      screen: "publishing",
      imageUrl,
      data,
      platforms: items.map((i) => i.platform),
      progress: initialProgress,
      labelImageUrl,
    });
    // Each platform: publish + poll until terminal (posted | failed). Push
    // per-platform completion into the publishing screen's `progress` so the
    // user sees each row tick over independently. One platform failing doesn't
    // take down the other.
    const outcomes: PublishOutcome[] = await Promise.all(
      items.map(async (item): Promise<PublishOutcome> => {
        let outcome: PublishOutcome;
        try {
          const job = await publishListing({
            listing_id: listingId,
            platform: item.platform,
            final_fields: item.finalFields,
          });
          const result = await pollPublishStatus(job.job_id);
          if (result.status === "posted" && result.platform_listing_url) {
            outcome = {
              platform: item.platform,
              listingUrl: result.platform_listing_url,
              error: null,
            };
          } else {
            outcome = {
              platform: item.platform,
              listingUrl: null,
              error: result.error ?? "Publish did not complete.",
            };
          }
        } catch (err) {
          outcome = {
            platform: item.platform,
            listingUrl: null,
            error: err instanceof Error ? err.message : String(err ?? "unknown"),
          };
        }
        setState((prev) => {
          if (prev.screen !== "publishing") return prev;
          return {
            ...prev,
            progress: {
              ...prev.progress,
              [item.platform]: outcome.listingUrl ? "posted" : "failed",
            },
          };
        });
        return outcome;
      }),
    );
    if (outcomes.every((o) => !o.listingUrl)) {
      // All failed — bounce back to results with the combined error so the user
      // can adjust and retry, instead of staring at an empty Published screen.
      setUploadError(
        "Publishing failed: " +
          outcomes.map((o) => `${o.platform} — ${o.error ?? "unknown"}`).join(" · "),
      );
      setState({ screen: "results", imageUrl, data, labelImageUrl });
      return;
    }
    setState({ screen: "published", outcomes, results: data });
  }

  async function handlePublishMany(items: PublishItem[]) {
    if (state.screen !== "results" || items.length === 0) return;
    const { data, imageUrl, labelImageUrl } = state;
    await _runPublishes(data.listing_id, items, data, imageUrl, labelImageUrl);
  }

  function handleReset() {
    uploadGenRef.current++; // invalidate any in-flight upload
    setUploadError(null);
    setState({ screen: "upload" });
  }

  async function handleOpenListing(listingId: string) {
    uploadGenRef.current++;
    setUploadError(null);
    try {
      const data = await fetchListingPrediction(listingId);
      setState({
        screen: "results",
        imageUrl: `${BASE}/listings/${listingId}/image`,
        data,
        // The tag photo, if one was uploaded — the <img> 404s + self-hides otherwise.
        labelImageUrl: `${BASE}/listings/${listingId}/label`,
      });
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : "Could not open listing.",
      );
    }
  }

  async function handleRelistListing(
    listingId: string,
    platforms: Platform[],
  ) {
    if (platforms.length === 0) return;
    uploadGenRef.current++;
    setUploadError(null);
    let data;
    try {
      data = await fetchListingPrediction(listingId);
    } catch (err) {
      setUploadError(
        err instanceof Error ? err.message : "Could not load listing for relist.",
      );
      return;
    }
    // Prefer Vinted when both were posted — matches the recommend logic on
    // ResultsScreen (Vinted typically has the larger fashion audience).
    const target: Platform = platforms.includes("vinted") ? "vinted" : platforms[0];
    const finalFields =
      target === "vinted" ? data.vinted.identification : data.kleinanzeigen.identification;
    const imageUrl = `${BASE}/listings/${listingId}/image`;
    await _runPublishes(listingId, [{ platform: target, finalFields }], data, imageUrl);
  }

  function renderScreen() {
    if (state.screen === "inventory") {
      return (
        <InventoryScreen
          onBack={() => setState({ screen: "upload" })}
          onOpenListing={handleOpenListing}
          onRelistListing={handleRelistListing}
        />
      );
    }
    if (state.screen === "upload") {
      return (
        <UploadScreen
          onSubmit={handleSubmit}
          onInventory={() => setState({ screen: "inventory" })}
          error={uploadError}
        />
      );
    }
    if (state.screen === "analyzing") {
      return (
        <AnalyzingScreen
          imageUrl={state.imageUrl}
          labelImageUrl={state.labelImageUrl}
          onCancel={handleReset}
        />
      );
    }
    if (state.screen === "results") {
      return (
        <ResultsScreen
          imageUrl={state.imageUrl}
          labelImageUrl={state.labelImageUrl}
          data={state.data}
          connectionStatus={connectionStatus}
          onPublishMany={handlePublishMany}
          onReset={handleReset}
          onConnectPlatform={setLoginModalPlatform}
          error={uploadError}
        />
      );
    }
    if (state.screen === "publishing") {
      return <PublishingScreen platforms={state.platforms} progress={state.progress} />;
    }
    if (state.screen === "published") {
      return (
        <PublishedScreen
          outcomes={state.outcomes}
          results={state.results}
          onReset={handleReset}
        />
      );
    }
    return null;
  }

  return (
    <>
      <PlatformConnectionBanner
        status={connectionStatus}
        onConnect={setLoginModalPlatform}
      />
      {renderScreen()}
      <PlatformLoginModal
        platform={loginModalPlatform}
        onClose={() => setLoginModalPlatform(null)}
        onSuccess={() => {
          setLoginModalPlatform(null);
          refreshStatus();
        }}
      />
    </>
  );
}
