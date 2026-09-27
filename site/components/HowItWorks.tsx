export default function HowItWorks() {
  return (
    <section id="how">
      <div className="section-head">
        <div className="eyebrow">three commands</div>
        <h2>Point at the mess. Get structure back.</h2>
      </div>
      <div className="cap-grid">
        <div className="cap">
          <div className="cap-visual">
            <div className="find-visual" aria-hidden="true">
              <div className="photo"></div>
              <div className="photo"></div>
              <div className="photo found" style={{ gridColumn: 3 }}>
                <span className="c2"></span>
              </div>
              <div className="photo"></div>
              <div className="photo"></div>
              <div className="photo"></div>
              <div className="photo"></div>
              <div className="photo"></div>
            </div>
          </div>
          <h3>find — one person</h3>
          <div className="result">6 matches → matched/</div>
        </div>
        <div className="cap">
          <div className="cap-visual">
            <div className="group-visual" aria-hidden="true">
              <div className="stack" style={{ ["--ring" as string]: "var(--cluster-a)" }}>
                <div className="photo"></div>
                <div className="photo"></div>
                <div className="photo"></div>
              </div>
              <div className="stack" style={{ ["--ring" as string]: "var(--cluster-b)" }}>
                <div className="photo"></div>
                <div className="photo"></div>
                <div className="photo"></div>
              </div>
              <div className="stack" style={{ ["--ring" as string]: "var(--cluster-c)" }}>
                <div className="photo"></div>
                <div className="photo"></div>
                <div className="photo"></div>
              </div>
            </div>
          </div>
          <h3>group — everyone, no references</h3>
          <div className="result">3 people in → 3 clusters out</div>
        </div>
        <div className="cap">
          <div className="cap-visual">
            <div className="dedupe-visual" aria-hidden="true">
              <div className="dupe-pair">
                <div className="photo"></div>
                <div className="photo"></div>
              </div>
              <svg
                className="dedupe-arrow"
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M5 12h14M13 6l6 6-6 6"></path>
              </svg>
              <div className="dedupe-result">
                <div className="photo"></div>
              </div>
            </div>
          </div>
          <h3>dedupe — collapse copies</h3>
          <div className="result">1 duplicate removed</div>
        </div>
      </div>
    </section>
  );
}
