"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { C } from "@/app/designTokens";
import { useIsMobile } from "@/hooks/useIsMobile";
import { slugForCardKey } from "@/lib/features";

export function WhySignInSection() {
  const t = useTranslations("auth.whySignIn");
  const isMobile = useIsMobile();

  const features = [
    { key: "routes", icon: <RouteIcon /> },
    { key: "history", icon: <HistoryIcon /> },
    { key: "contacts", icon: <ContactsIcon /> },
    { key: "notifications", icon: <BellIcon /> },
  ] as const;

  return (
    <section
      style={{
        padding: isMobile ? "60px 24px" : "80px 96px",
        maxWidth: 1440,
        margin: "0 auto",
      }}
    >
      <div style={{ maxWidth: 880, marginBottom: isMobile ? 32 : 48 }}>
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
          <Link
            key={f.key}
            href={`/${slugForCardKey(f.key)}`}
            className="block rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-[#C8512C]/40"
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <div
              className="rounded-2xl bg-white p-6 transition-colors"
              style={{ border: "1px solid rgba(200,81,44,0.15)" }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.borderColor = "rgba(200,81,44,0.35)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.borderColor = "rgba(200,81,44,0.15)")
              }
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
          </Link>
        ))}
      </div>
    </section>
  );
}

function RouteIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="6" cy="19" r="3" />
      <circle cx="18" cy="5" r="3" />
      <path d="M6.7 17.3L17.3 6.7" />
    </svg>
  );
}

function HistoryIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
      <path d="M12 7v5l3 2" />
    </svg>
  );
}

function ContactsIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  );
}
