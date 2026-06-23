"use client";

import { useTranslations } from "next-intl";
import { C } from "@/app/designTokens";
import { useIsMobile } from "@/hooks/useIsMobile";

export function WhySignInSection() {
  const t = useTranslations("auth.whySignIn");
  const isMobile = useIsMobile();

  const features = [
    { key: "routes", icon: <StepIcon n={1} /> },
    { key: "history", icon: <StepIcon n={2} /> },
    { key: "contacts", icon: <StepIcon n={3} /> },
    { key: "notifications", icon: <StepIcon n={4} /> },
  ] as const;

  return (
    <section
      id="how-it-works"
      style={{
        padding: isMobile ? "60px 24px" : "100px 96px",
        maxWidth: 1440,
        margin: "0 auto",
        scrollMarginTop: 80,
      }}
    >
      <div style={{ maxWidth: 880, marginBottom: isMobile ? 32 : 56 }}>
        <div
          style={{
            fontFamily: C.M,
            fontSize: 11,
            letterSpacing: "0.18em",
            color: C.purple,
            fontWeight: 500,
            marginBottom: 12,
          }}
        >
          {t("eyebrow")}
        </div>
        <h2
          style={{
            fontFamily: C.D,
            fontSize: "clamp(28px, 4vw, 52px)",
            fontWeight: 600,
            color: C.text,
            lineHeight: 1.1,
            letterSpacing: "-0.02em",
            margin: "0 0 16px",
          }}
        >
          {t("heading")}
        </h2>
        <p
          style={{
            fontFamily: C.D,
            fontSize: 15,
            color: C.sub,
            lineHeight: 1.6,
            margin: 0,
            maxWidth: 680,
          }}
        >
          {t("subheading")}
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {features.map((f) => (
          <div
            key={f.key}
            className="block rounded-2xl"
          >
            <div
              className="rounded-2xl bg-white p-6 h-full"
              style={{ border: "1px solid rgba(200,81,44,0.15)" }}
            >
              <div className="flex items-start gap-4">
                <div
                  className="h-10 w-10 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{
                    background: "rgba(200,81,44,0.08)",
                    color: "#C8512C",
                  }}
                >
                  {f.icon}
                </div>
                <div>
                  <h3
                    className="text-lg font-semibold mb-1"
                    style={{ color: "#2C2C2A" }}
                  >
                    {t(`${f.key}.title`)}
                  </h3>
                  <p
                    className="text-sm leading-relaxed"
                    style={{ color: "#888780" }}
                  >
                    {t(`${f.key}.description`)}
                  </p>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function StepIcon({ n }: { n: number }) {
  return (
    <span
      style={{
        fontFamily: C.D,
        fontSize: 16,
        fontWeight: 700,
        color: "#C8512C",
        lineHeight: 1,
      }}
    >
      {n}
    </span>
  );
}
