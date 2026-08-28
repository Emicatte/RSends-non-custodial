"use client";

import { useSession } from "next-auth/react";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import { useState, useRef, useEffect } from "react";
import { performLogout } from "@/lib/logoutClient";
import { C } from "@/app/designTokens";

/**
 * @param onDark render against the terracotta-deep marketing nav. Additive:
 *   the default is the original light styling, so the component stays usable
 *   on a light surface even though MarketingNav is currently its only caller.
 *
 * The dropdown panel is a floating light surface in both modes — only the
 * controls that sit ON the bar flip.
 */
export function LandingAuthButtons({ onDark = false }: { onDark?: boolean } = {}) {
  const { data: session, status } = useSession();
  const t = useTranslations("auth");
  const locale = useLocale();
  const [menuOpen, setMenuOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [signOutFailed, setSignOutFailed] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    if (menuOpen) document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [menuOpen]);

  if (status === "loading") {
    return (
      <div
        className="h-9 w-[180px] animate-pulse"
        style={{
          background: onDark ? "rgba(255,255,255,0.18)" : "rgba(200,81,44,0.08)",
          borderRadius: 4,
        }}
        aria-hidden
      />
    );
  }

  if (status === "authenticated" && session?.user) {
    const name = session.user.name || session.user.email || "User";
    const initials = name
      .split(" ")
      .map((s) => s[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();

    return (
      <div className="relative" ref={menuRef}>
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="flex items-center gap-2 px-2 py-1.5 transition-colors"
          style={{
            borderRadius: 4,
            background: onDark ? "rgba(255,255,255,0.12)" : C.surface,
            border: `1px solid ${onDark ? "rgba(255,255,255,0.28)" : "rgba(200,81,44,0.2)"}`,
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = onDark ? "rgba(255,255,255,0.5)" : "rgba(200,81,44,0.4)")}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = onDark ? "rgba(255,255,255,0.28)" : "rgba(200,81,44,0.2)")}
          aria-label={t("accountMenu")}
          aria-expanded={menuOpen}
        >
          {session.user.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={session.user.image} alt="" className="h-6 w-6 rounded-full" />
          ) : (
            <div
              className="h-6 w-6 rounded-full text-[10px] font-semibold flex items-center justify-center"
              style={
                onDark
                  ? { background: C.onDark, color: C.terracottaDeep }
                  : { background: C.terracottaDeep, color: C.onDark }
              }
            >
              {initials}
            </div>
          )}
          <span
            className="text-sm max-w-[120px] truncate"
            style={{ color: onDark ? C.onDark : C.text }}
          >
            {name}
          </span>
          <svg width="10" height="10" viewBox="0 0 10 10" style={{ color: onDark ? C.onDarkMuted : C.sub }}>
            <path
              d="M2 3.5L5 6.5L8 3.5"
              stroke="currentColor"
              strokeWidth="1.5"
              fill="none"
              strokeLinecap="round"
            />
          </svg>
        </button>

        {menuOpen && (
          <div
            className="absolute right-0 top-full mt-2 w-56 shadow-lg py-1 z-50"
            style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8 }}
          >
            <Link
              href={`/${locale}/app`}
              className="block px-4 py-2 text-sm transition-colors"
              style={{ color: C.text }}
              onMouseEnter={(e) => (e.currentTarget.style.background = C.terracottaWash)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              onClick={() => setMenuOpen(false)}
            >
              {t("openDashboard")}
            </Link>
            <Link
              href={`/${locale}/settings`}
              className="block px-4 py-2 text-sm transition-colors"
              style={{ color: C.text, textDecoration: "none" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = C.terracottaWash)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              onClick={() => setMenuOpen(false)}
            >
              {t("settings")}
            </Link>
            <div
              className="my-1"
              style={{ borderTop: `1px solid ${C.border}` }}
            />
            <button
              disabled={signingOut}
              onClick={async () => {
                setSigningOut(true);
                setSignOutFailed(false);
                // Blocking logout: server session revoked first; the menu
                // stays open and shows the error if revocation fails.
                const { ok } = await performLogout({ callbackUrl: `/${locale}` });
                if (!ok) {
                  setSignOutFailed(true);
                  setSigningOut(false);
                } else {
                  setMenuOpen(false);
                }
              }}
              className="block w-full text-left px-4 py-2 text-sm transition-colors disabled:opacity-50"
              style={{ color: C.text }}
              onMouseEnter={(e) => (e.currentTarget.style.background = C.terracottaWash)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              {signingOut ? t("signingOut") : t("signOut")}
            </button>
            {signOutFailed && (
              <p role="alert" className="px-4 py-1 text-xs" style={{ color: C.terracottaDeep }}>
                {t("signOutError")}
              </p>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Link
        href={`/${locale}/login`}
        className="hidden sm:inline-flex text-sm px-3 py-1.5 transition-colors"
        style={{ color: onDark ? C.onDark : C.text, textDecoration: "none" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = onDark ? C.terracottaWash : C.terracottaDeep)}
        onMouseLeave={(e) => (e.currentTarget.style.color = onDark ? C.onDark : C.text)}
      >
        {t("signIn")}
      </Link>
      <Link
        href={`/${locale}/signup`}
        className="flex items-center gap-2 text-sm font-medium px-4 py-1.5 transition-colors"
        style={{
          borderRadius: 4,
          background: onDark ? C.onDark : C.terracottaDeep,
          color: onDark ? C.terracottaDeep : C.onDark,
          textDecoration: "none",
        }}
        onMouseEnter={(e) => (e.currentTarget.style.background = onDark ? C.terracottaWash : "#8F3517")}
        onMouseLeave={(e) => (e.currentTarget.style.background = onDark ? C.onDark : C.terracottaDeep)}
      >
        {t("signUp")}
      </Link>
    </div>
  );
}

