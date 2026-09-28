export default function Demo() {
  return (
    <section id="demo">
      <div className="section-head">
        <div className="eyebrow">real run, real archive</div>
        <h2>19 photos, 3 people, 2010–2025</h2>
      </div>
      <div className="demo-strip">
        <div className="stat">
          <div className="n">6/6</div>
          <div className="l">real matches found</div>
        </div>
        <div className="stat">
          <div className="n">13/13</div>
          <div className="l">true negatives rejected</div>
        </div>
        <div className="stat">
          <div className="n">0.155</div>
          <div className="l">highest false-positive score</div>
        </div>
        <div className="stat">
          <div className="n">3</div>
          <div className="l">people clustered, no references</div>
        </div>
      </div>
      <div className="demo-groups" aria-hidden="true">
        <div>
          <div className="order-group-label">
            <span className="dot" style={{ background: "var(--cluster-a)" }}></span>
            person_001/
          </div>
          <div className="order-row" style={{ ["--ring" as string]: "var(--cluster-a)" }}>
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
            <div className="photo"><img src="/demo/hiddleston_09.jpg" alt="Tom Hiddleston" /></div>
            <div className="photo"><img src="/demo/hiddleston_10.jpg" alt="Tom Hiddleston" /></div>
            <div className="photo"><img src="/demo/hiddleston_11.jpg" alt="Tom Hiddleston" /></div>
          </div>
        </div>
        <div>
          <div className="order-group-label">
            <span className="dot" style={{ background: "var(--cluster-c)" }}></span>
            person_003/
          </div>
          <div className="order-row" style={{ ["--ring" as string]: "var(--cluster-c)" }}>
            <div className="photo"><img src="/demo/evans_07.jpg" alt="Chris Evans" /></div>
            <div className="photo"><img src="/demo/evans_09.jpg" alt="Chris Evans" /></div>
            <div className="photo"><img src="/demo/evans_04.jpg" alt="Chris Evans" /></div>
          </div>
        </div>
      </div>
    </section>
  );
}
