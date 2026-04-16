export default function Landing() {
  return (
    <div className="space-y-16">
      <section className="text-center pt-10">
        <h1 className="text-5xl font-semibold tracking-tight">
          Applications that actually get sent.
        </h1>
        <p className="mt-5 text-lg text-white/70 max-w-2xl mx-auto">
          Instaply files real applications on your behalf — Greenhouse, Lever,
          SmartRecruiters and more. Pay only when the confirmation email lands.
        </p>
        <div className="mt-8 flex justify-center gap-4">
          <a href="/signup"
             className="rounded-md bg-accent px-5 py-3 text-sm font-medium">
            Start — 3 free applications
          </a>
          <a href="#pricing" className="rounded-md border border-white/20 px-5 py-3 text-sm">
            See pricing
          </a>
        </div>
      </section>

      <section id="pricing" className="grid md:grid-cols-3 gap-4">
        {[
          { id: "starter", label: "Starter", usd: 10, credits: 10, bonus: 0 },
          { id: "plus",    label: "Plus",    usd: 25, credits: 30, bonus: 17 },
          { id: "pro",     label: "Pro",     usd: 50, credits: 70, bonus: 40 },
        ].map((p) => (
          <div key={p.id} className="rounded-xl border border-white/10 p-6">
            <div className="text-sm text-white/60">{p.label}</div>
            <div className="mt-2 text-3xl font-semibold">${p.usd}</div>
            <div className="mt-1 text-white/80">{p.credits} applications</div>
            {p.bonus > 0 && (
              <div className="mt-1 text-xs text-accent">+{p.bonus}% bonus</div>
            )}
            <a href="/billing"
               className="mt-5 inline-block text-sm underline text-white/80">
              Top up →
            </a>
          </div>
        ))}
      </section>

      <section className="rounded-xl border border-white/10 p-6 text-sm text-white/70">
        <strong className="text-white">How it works.</strong> Sign up → upload your
        resume + answer 5 questions once → connect Claude (or use the web)
        → we submit applications and wait for the employer confirmation.
        Credit is deducted only after confirmation.
      </section>
    </div>
  );
}
