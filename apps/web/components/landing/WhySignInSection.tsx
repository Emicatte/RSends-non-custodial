"use client";

import Image from "next/image";
import { useRef, useLayoutEffect, useEffect } from "react";
import { useTranslations } from "next-intl";
import { FileText, Wallet, Link2, Webhook, type LucideIcon } from "lucide-react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { C } from "@/app/designTokens";
import { useIsMobile } from "@/hooks/useIsMobile";
import ScrubCascade from "@/components/motion/ScrubCascade";

gsap.registerPlugin(ScrollTrigger);

// useLayoutEffect on the client, useEffect on the server (avoids the SSR warning
// since "use client" components still render once on the server in the App Router).
const useIsoLayoutEffect = typeof window !== "undefined" ? useLayoutEffect : useEffect;

const SKYSCRAPER = "/grattacieli/skyscraper.jpg";

const STEPS: { key: string; Icon: LucideIcon }[] = [
  { key: "routes", Icon: FileText },
  { key: "history", Icon: Wallet },
  { key: "contacts", Icon: Link2 },
  { key: "notifications", Icon: Webhook },
];

export function WhySignInSection() {
  const t = useTranslations("auth.whySignIn");
  const isMobile = useIsMobile();
  const leftRef = useRef<HTMLDivElement>(null);

  useIsoLayoutEffect(() => {
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      const el = leftRef.current;
      if (!el) return;
      const ctx = gsap.context(() => {
        // EXACTLY ONE tween for the whole left column, on the outer container.
        // Fade only (no y) => the building can never slide inside the rounded frame.
        gsap.fromTo(
          el,
          { autoAlpha: 0 },
          {
            autoAlpha: 1,
            ease: "none",
            scrollTrigger: { trigger: el, start: "top 88%", end: "top 60%", scrub: 0.5 },
          },
        );
      }, el);
      // Recompute start/end once webfonts settle (layout shift), then clean up.
      if (typeof document !== "undefined" && document.fonts?.ready) {
        document.fonts.ready.then(() => ScrollTrigger.refresh());
      }
      return () => ctx.revert();
    });
    return () => mm.revert();
  }, []);

  return (
    <section
      id="how-it-works"
      style={{
        padding: isMobile ? "72px 24px" : "120px 96px",
        maxWidth: 1440,
        margin: "0 auto",
        scrollMarginTop: 80,
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "0.84fr 1.16fr",
          alignItems: "stretch",
          borderRadius: 24,
          overflow: "hidden",
          background: C.bg,
          border: `1px solid ${C.border}`,
        }}
      >
        {/* Left: skyscraper image with overlaid copy */}
        <div
          ref={leftRef}
          style={{
            position: "relative",
            minHeight: isMobile ? 280 : undefined,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <Image
            src={SKYSCRAPER}
            alt=""
            fill
            sizes="(max-width: 768px) 100vw, 40vw"
            priority
            style={{ objectFit: "cover" }}
          />
          <div
            style={{
              position: "absolute",
              inset: 0,
              background: "rgba(10,10,10,0.38)",
            }}
          />
          <div
            style={{
              position: "relative",
              display: "flex",
              flexDirection: "column",
              padding: "26px 24px",
            }}
          >
            <div
              style={{
                fontFamily: C.M,
                fontSize: 12,
                letterSpacing: "2px",
                textTransform: "uppercase",
                color: "#E8A488",
                fontWeight: 500,
                marginBottom: 14,
              }}
            >
              {t("eyebrow")}
            </div>
            <h2
              style={{
                fontFamily: C.D,
                fontSize: isMobile ? 28 : 32,
                fontWeight: 600,
                color: "#FFFFFF",
                lineHeight: 1.1,
                letterSpacing: "-0.5px",
                margin: "0 0 14px",
              }}
            >
              {t("heading")}
            </h2>
            <p
              style={{
                fontFamily: C.D,
                fontSize: 14,
                color: "rgba(255,255,255,0.82)",
                lineHeight: 1.5,
                margin: 0,
                maxWidth: 240,
              }}
            >
              {t("subheading")}
            </p>
          </div>
        </div>

        {/* Right: 2×2 grid of step cards */}
        <ScrubCascade style={{ padding: 22 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(0,1fr))",
              gap: 18,
              alignContent: "center",
              height: "100%",
            }}
          >
            {STEPS.map(({ key, Icon }, i) => (
              <div
                key={key}
                className="rs-card"
                style={{
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: 16,
                  padding: 28,
                  minHeight: 210,
                  display: "flex",
                  flexDirection: "column",
                  gap: 12,
                }}
              >
                <div
                  style={{
                    width: 48,
                    height: 48,
                    borderRadius: 12,
                    background: "#F6E6DF",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  <Icon size={22} color={C.purple} strokeWidth={2} aria-hidden />
                </div>
                <div
                  style={{
                    fontFamily: C.M,
                    fontSize: 11,
                    letterSpacing: "1.5px",
                    textTransform: "uppercase",
                    color: C.purple,
                    fontWeight: 500,
                  }}
                >
                  {`Step ${i + 1}`}
                </div>
                <h3
                  style={{
                    fontFamily: C.D,
                    fontSize: 19,
                    fontWeight: 600,
                    color: C.text,
                    margin: 0,
                  }}
                >
                  {t(`${key}.title`)}
                </h3>
                <p
                  style={{
                    fontFamily: C.D,
                    fontSize: 14.5,
                    color: C.sub,
                    lineHeight: 1.6,
                    margin: 0,
                  }}
                >
                  {t(`${key}.description`)}
                </p>
              </div>
            ))}
          </div>
        </ScrubCascade>
      </div>
    </section>
  );
}
