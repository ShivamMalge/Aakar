import { notFound } from "next/navigation";

import { goldenTopics, loadGoldenSpec } from "@/specs/load";
import { DEFAULT_OPTIONS, Viewer, type ViewerOptions } from "@/viewer/Viewer";

type SearchParams = Record<string, string | string[] | undefined>;

function one(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function flag(value: string | string[] | undefined, fallback: boolean): boolean {
  const raw = one(value);
  if (raw === undefined) return fallback;
  return raw === "1" || raw === "true";
}

function readOptions(search: SearchParams): Partial<ViewerOptions> {
  const angle = Number.parseInt(one(search["angle"]) ?? "0", 10);
  const explode = Number.parseFloat(one(search["explode"]) ?? "0");
  const mode = one(search["mode"]);

  return {
    angle: Number.isFinite(angle) ? angle : 0,
    shot: flag(search["shot"], false),
    cutaway: flag(search["cutaway"], DEFAULT_OPTIONS.cutaway),
    labels: flag(search["labels"], DEFAULT_OPTIONS.labels),
    explode: Number.isFinite(explode) ? Math.min(Math.max(explode, 0), 1) : 0,
    explodeMode: mode === "per-part" ? "per-part" : "top-level",
  };
}

export function generateStaticParams(): Array<{ topic: string }> {
  return goldenTopics().map((topic) => ({ topic }));
}

export default function RenderPage({
  params,
  searchParams,
}: {
  params: { topic: string };
  searchParams: SearchParams;
}) {
  // D-004: the draft selector must fail closed. Phase 1 has no spec_versions rows and
  // no owner session to gate them with, so an explicit refusal beats quietly serving
  // the approved spec under a URL that asked for a draft.
  if (one(searchParams["spec_version"]) !== undefined) {
    return (
      <main className="viewer-error" role="alert">
        <h2>Draft specs are not addressable yet</h2>
        <p>
          <code>?spec_version=</code> resolves a specific row in <code>spec_versions</code>{" "}
          behind the owner session (D-004). That table is written in Phase 3; Phase 1
          serves the hand-written golden specs only.
        </p>
      </main>
    );
  }

  const result = loadGoldenSpec(params.topic);
  if (!result.ok && result.reason === "not-found") notFound();

  if (!result.ok) {
    return (
      <main className="viewer-error" role="alert">
        <h2>This spec is not schema-valid</h2>
        <ul>
          {result.errors.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      </main>
    );
  }

  return <Viewer spec={result.spec} options={readOptions(searchParams)} />;
}
