import WaitlistForm from "./WaitlistForm";

export default function Pricing() {
  return (
    <section id="get">
      <div className="section-head">
        <div className="eyebrow">get facematch</div>
        <h2>One-time purchase.</h2>
      </div>
      <div className="price-card">
        <div className="price-top">
          <div className="price-name">facematch</div>
          <div className="price-amount">
            $19<span className="per"> one-time</span>
          </div>
        </div>
        <ul className="price-features">
          <li>find one person (or several at once), group, and dedupe</li>
          <li>macOS &amp; Linux, single binary</li>
          <li>Runs entirely offline, always</li>
          <li>Free updates</li>
        </ul>
        <WaitlistForm />
      </div>
    </section>
  );
}
