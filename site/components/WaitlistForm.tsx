"use client";

import { useState, type FormEvent } from "react";

export default function WaitlistForm() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    // TODO: wire up real Stripe Checkout call here once payment is ready.
    setMessage("Checkout coming soon — we'll email you the moment it's live.");
  }

  return (
    <>
      <form className="waitlist-form" onSubmit={handleSubmit}>
        <label
          htmlFor="waitlist-email"
          style={{
            position: "absolute",
            width: "1px",
            height: "1px",
            overflow: "hidden",
            clip: "rect(0 0 0 0)",
          }}
        >
          Email address
        </label>
        <input
          id="waitlist-email"
          type="email"
          placeholder="you@email.com"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <button type="submit">Buy access</button>
      </form>
      <p className="form-msg">{message}</p>
    </>
  );
}
