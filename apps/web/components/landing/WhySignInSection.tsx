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
  const textRef = useRef<HTMLDivElement>(null);

  useIsoLayoutEffect(() => {
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      const root = textRef.current;
      if (!root) return;
      const ctx = gsap.context(() => {
        // The building image + frame stay STATIC (fully visible, no tween). Only the
        // copy overlaid on the photo animates: eyebrow -> heading -> subcopy fade-up
        // in a small index cascade, scrubbed by scroll.
        const txt = gsap.utils.selector(root)(".rs-hiw-text");
        txt.forEach((el, i) => {
          gsap.fromTo(
            el,
            { autoAlpha: 0, y: 28 },
            {
              autoAlpha: 1,
              y: 0,
              ease: "none",
              scrollTrigger: {
                trigger: el,
                start: `top ${86 - i * 4}%`,
                end: `top ${66 - i * 4}%`,
                scrub: 0.5,
              },
            },
          );
        });
      }, root);
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
      style={{
        padding: isMobile ? "72px 24px" : "120px 96px",
        maxWidth: 1440,
        margin: "0 auto",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isMobile ? "1fr" : "0.84fr 1.16fr",
          alignItems: "stretch",
          borderRadius: 24,
          background: C.bg,
          border: `1px solid ${C.border}`,
        }}
      >
        {/* Left: skyscraper image with overlaid copy — STATIC (no animation). */}
        <div
          style={{
            position: "relative",
            minHeight: isMobile ? 280 : undefined,
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
            // Rounded clip frame for the image. Round only the OUTER corners
            // (the inner seam between the two columns stays square).
            borderRadius: isMobile ? "24px 24px 0 0" : "24px 0 0 24px",
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
            ref={textRef}
            style={{
              position: "relative",
              display: "flex",
              flexDirection: "column",
              padding: "26px 24px",
            }}
          >
            <div
              className="rs-hiw-text"
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
              className="rs-hiw-text"
              style={{
                fontFamily: C.D,
                fontSize: isMobile ? 28 : 32,
                fontWeight: 600,
                color: "#FFFFFF",
                lineHeight: 1.1,
                letterSpacing: "-0.5px",
                margin: "0 0 14px",
                textWrap: "balance",
              }}
            >
              {t("heading")}
            </h2>
            <p
              className="rs-hiw-text"
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
              // Single full-width column on mobile; from the breakpoint up,
              // two-up only when each card gets ≥240px (same auto-fit pattern
              // as the /how-it-works steps). A fixed 2-col grid squeezed cards
              // to ~140px at 351–430px AND at the 768px tablet boundary, where
              // the outer image/cards split leaves this column ~330px — body
              // text wrapped one word per line.
              gridTemplateColumns: isMobile
                ? "1fr"
                : "repeat(auto-fit, minmax(240px, 1fr))",
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
                  padding: isMobile ? 22 : 28,
                  // Stacked cards hug their content; the fixed height only
                  // equalizes the desktop 2×2 grid.
                  minHeight: isMobile ? 0 : 210,
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
