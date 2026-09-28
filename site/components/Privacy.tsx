export default function Privacy() {
  return (
    <section>
      <div className="privacy">
        <div className="privacy-icon">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="var(--ok)"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="4" y="11" width="16" height="9" rx="1.5"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
        </div>
        <p>Fully local. No network calls, no accounts, no telemetry.</p>
      </div>
    </section>
  );
}
