"use client";

import { signOut, useSession } from "next-auth/react";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import { useState, useRef, useEffect } from "react";

export function LandingAuthButtons() {
  const { data: session, status } = useSession();
  const t = useTranslations("auth");
  const locale = useLocale();
  const [menuOpen, setMenuOpen] = useState(false);
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
        className="h-9 w-[180px] animate-pulse rounded-lg"
        style={{ background: "rgba(200,81,44,0.08)" }}
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
          className="flex items-center gap-2 rounded-lg bg-white px-2 py-1.5 transition-colors"
          style={{ border: "1px solid rgba(200,81,44,0.2)" }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = "rgba(200,81,44,0.4)")}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = "rgba(200,81,44,0.2)")}
          aria-label={t("accountMenu")}
          aria-expanded={menuOpen}
        >
          {session.user.image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={session.user.image} alt="" className="h-6 w-6 rounded-full" />
          ) : (
            <div
              className="h-6 w-6 rounded-full text-white text-[10px] font-semibold flex items-center justify-center"
              style={{ background: "#C8512C" }}
            >
              {initials}
            </div>
          )}
          <span
            className="text-sm max-w-[120px] truncate"
            style={{ color: "#2C2C2A" }}
          >
            {name}
          </span>
          <svg width="10" height="10" viewBox="0 0 10 10" style={{ color: "#888780" }}>
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
            className="absolute right-0 top-full mt-2 w-56 rounded-xl bg-white shadow-lg py-1 z-50"
            style={{ border: "1px solid rgba(200,81,44,0.2)" }}
          >
            <Link
              href={`/${locale}/app`}
              className="block px-4 py-2 text-sm transition-colors"
              style={{ color: "#2C2C2A" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(200,81,44,0.06)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              onClick={() => setMenuOpen(false)}
            >
              {t("openDashboard")}
            </Link>
            <Link
              href={`/${locale}/settings`}
              className="block px-4 py-2 text-sm transition-colors"
              style={{ color: "#2C2C2A", textDecoration: "none" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(200,81,44,0.06)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              onClick={() => setMenuOpen(false)}
            >
              {t("settings")}
            </Link>
            <div
              className="my-1"
              style={{ borderTop: "1px solid rgba(200,81,44,0.15)" }}
            />
            <button
              onClick={() => {
                setMenuOpen(false);
                signOut({ callbackUrl: `/${locale}` });
              }}
              className="block w-full text-left px-4 py-2 text-sm transition-colors"
              style={{ color: "#2C2C2A" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(200,81,44,0.06)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              {t("signOut")}
            </button>
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
        style={{ color: "#2C2C2A", textDecoration: "none" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "#C8512C")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "#2C2C2A")}
      >
        {t("signIn")}
      </Link>
      <Link
        href={`/${locale}/signup`}
        className="flex items-center gap-2 rounded-lg text-white text-sm font-medium px-4 py-1.5 transition-colors"
        style={{ background: "#C8512C", textDecoration: "none" }}
        onMouseEnter={(e) => (e.currentTarget.style.background = "#B04424")}
        onMouseLeave={(e) => (e.currentTarget.style.background = "#C8512C")}
      >
        {t("signUp")}
      </Link>
    </div>
  );
}

