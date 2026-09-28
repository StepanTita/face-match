export default function Hero() {
  return (
    <section className="hero" style={{ borderTop: "none" }}>
      <div className="eyebrow">runs 100% offline</div>
      <h1>Chaos in. Structure out.</h1>
      <p className="hero-sub">
        Point facematch at terabytes of unsorted photos and videos. Get one
        person&apos;s photos, everyone sorted by face, or the duplicates gone.
      </p>
      <div className="hero-actions">
        <a className="btn btn-primary" href="#get">
          Get access
        </a>
        <a className="btn btn-ghost" href="#demo">
          See it work
        </a>
      </div>
      <div className="cmd-pill">
        $ facematch find{" "}
        <span className="accent">
          --sources ~/Photos ~/icloud_export.zip
        </span>
      </div>

      <div className="flow">
        <div className="flow-panel">
          <div className="flow-label">a few terabytes, no structure</div>
          <div className="chaos-grid" aria-hidden="true">
            <div className="photo">
              <img src="/demo/evans_01.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/watson_04.jpg" alt="" />
            </div>
            <div className="photo found">
              <img src="/demo/hiddleston_07.jpg" alt="" />
              <span className="c2"></span>
            </div>
            <div className="photo">
              <img src="/demo/evans_06.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/watson_02.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/hiddleston_09.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/evans_09.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/watson_06.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/hiddleston_10.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/evans_04.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/watson_07.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/hiddleston_11.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/evans_07.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/watson_08.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/hiddleston_08.jpg" alt="" />
            </div>
            <div className="photo">
              <img src="/demo/watson_01.jpg" alt="" />
            </div>
          </div>
        </div>
        <svg
          className="flow-arrow"
          width="28"
          height="28"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M5 12h14M13 6l6 6-6 6"></path>
        </svg>
        <div className="flow-panel">
          <div className="flow-label">facematch group / find / dedupe</div>
          <div className="order-groups" aria-hidden="true">
            <div>
              <div className="order-group-label">
                <span className="dot" style={{ background: "var(--cluster-a)" }}></span>
                person_001/
              </div>
              <div className="order-row" style={{ ["--ring" as string]: "var(--cluster-a)" }}>
                <div className="photo"><img src="/demo/watson_01.jpg" alt="Emma Watson" /></div>
                <div className="photo"><img src="/demo/watson_02.jpg" alt="Emma Watson" /></div>
                <div className="photo"><img src="/demo/watson_03.jpg" alt="Emma Watson" /></div>
                <div className="photo"><img src="/demo/watson_04.jpg" alt="Emma Watson" /></div>
                <div className="photo"><img src="/demo/watson_06.jpg" alt="Emma Watson" /></div>
                <div className="photo"><img src="/demo/watson_07.jpg" alt="Emma Watson" /></div>
              </div>
            </div>
            <div>
              <div className="order-group-label">
                <span className="dot" style={{ background: "var(--cluster-b)" }}></span>
                person_002/
              </div>
              <div className="order-row" style={{ ["--ring" as string]: "var(--cluster-b)" }}>
                <div className="photo"><img src="/demo/hiddleston_07.jpg" alt="Tom Hiddleston" /></div>
                <div className="photo"><img src="/demo/hiddleston_08.jpg" alt="Tom Hiddleston" /></div>
                <div className="photo"><img src="/demo/hiddleston_09.jpg" alt="Tom Hiddleston" /></div>
                <div className="photo"><img src="/demo/hiddleston_10.jpg" alt="Tom Hiddleston" /></div>
                <div className="photo"><img src="/demo/hiddleston_11.jpg" alt="Tom Hiddleston" /></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
