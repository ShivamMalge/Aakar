import Link from "next/link";

import { goldenTopics, loadGoldenSpec } from "@/specs/load";

export default function Home() {
  const topics = goldenTopics();

  return (
    <main className="home">
      <h1>Aakar</h1>
      <p className="lede">
        Hand-written SceneSpecs, rendered by the deterministic compiler. No model has
        touched any of this — generation arrives in Phase 3.
      </p>

      <h2>Golden topics</h2>
      <ul>
        {topics.map((topic) => {
          const result = loadGoldenSpec(topic);
          return (
            <li key={topic}>
              <Link href={`/render/${topic}`}>
                <strong>{result.ok ? result.spec.title : topic}</strong>
                <br />
                <span className="phase">
                  <code>{topic}</code>
                  {result.ok ? ` · ${result.spec.parts.length} parts` : " · does not parse"}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>

      <p className="phase">Phase 1 — compiler + viewer, zero LLM calls.</p>
    </main>
  );
}
